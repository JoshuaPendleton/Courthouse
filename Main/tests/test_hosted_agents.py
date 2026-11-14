"""Cross-platform integration checks using synthetic GGUF headers, not a scripted red team."""
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import courthouse
import local_engine


class HostedAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.agents = self.root / 'agents'
        self.uploads = self.root / 'uploads'
        self.agents.mkdir()
        self.uploads.mkdir()
        self.prev_dir = local_engine.DIR
        self.prev_hosted = local_engine.HOSTED_DIR
        self.prev_registry = local_engine.REGISTRY.copy()
        self.prev_agents = local_engine.HOSTED_AGENTS[:]
        self.prev_status = local_engine.HOSTED_STATUS.copy()
        self.prev_fp = local_engine._HOSTED_FINGERPRINT
        self.prev_preload = local_engine._PRELOAD_PREFERRED
        local_engine.DIR = self.uploads
        local_engine.HOSTED_DIR = self.agents.resolve()
        local_engine.REGISTRY.clear()
        local_engine.HOSTED_AGENTS = []
        local_engine.HOSTED_STATUS = {'ready':False,'error':'not set'}
        local_engine._HOSTED_FINGERPRINT = None
        local_engine._PRELOAD_PREFERRED = None
        local_engine._CACHE.clear()

    def tearDown(self):
        local_engine.DIR = self.prev_dir
        local_engine.HOSTED_DIR = self.prev_hosted
        local_engine.REGISTRY.clear()
        local_engine.REGISTRY.update(self.prev_registry)
        local_engine.HOSTED_AGENTS = self.prev_agents
        local_engine.HOSTED_STATUS = self.prev_status
        local_engine._HOSTED_FINGERPRINT = self.prev_fp
        local_engine._PRELOAD_PREFERRED = self.prev_preload
        local_engine._CACHE.clear()
        self.temp.cleanup()

    def write_agents(self, names=('alpha.gguf', 'beta.gguf', 'gamma.gguf'), duplicate=False):
        for i, name in enumerate(names):
            byte = 1 if (duplicate and i == len(names) - 1) else (i + 1)
            (self.agents / name).write_bytes(b'GGUF' + bytes([byte]) * 16)

    def test_missing_hosted_weights_blocks_assessment(self):
        state = local_engine.initialize_hosted_agents(preload=False)
        self.assertFalse(state['ready'])
        self.assertIn('No GGUF', state['error'])
        with self.assertRaisesRegex(ValueError, 'not ready'):
            local_engine.validate_hosted_assessment('unknown-target')

    def test_hosted_models_register_from_directory_and_preload(self):
        self.write_agents()
        loaded = []
        def load(model_id):
            loaded.append(model_id)
            return object()
        with patch.object(local_engine, '_has_llama', return_value=True), patch.object(local_engine, '_get_llm', side_effect=load):
            status = local_engine.initialize_hosted_agents(preload=True)
        self.assertTrue(status['ready'])
        self.assertTrue(status['preloaded'])
        self.assertEqual(loaded, ['courthouse-agent-1', 'courthouse-agent-2', 'courthouse-agent-3'])
        self.assertEqual([m['name'] for m in local_engine.HOSTED_AGENTS],
                         ['alpha.gguf', 'beta.gguf', 'gamma.gguf'])
        self.assertTrue(all(x['status'] == 'loaded' for x in status['agents']))
        target_bytes = b'GGUF' + b'Z' * 16
        target = local_engine.save_upload(io.BytesIO(target_bytes), len(target_bytes), 'target.gguf')
        actual, agents = local_engine.validate_hosted_assessment(target['model_id'])
        self.assertEqual(actual['name'], 'target.gguf')
        self.assertEqual(len(agents), 3)
        self.assertFalse(any(a['source'] != 'server_hosted' for a in agents))

    def test_selected_agents_subset(self):
        self.write_agents()
        with patch.object(local_engine, '_has_llama', return_value=True):
            local_engine.initialize_hosted_agents(preload=False)
        target_bytes = b'GGUF' + b'Y' * 16
        target = local_engine.save_upload(io.BytesIO(target_bytes), len(target_bytes), 'target.gguf')
        tid = target['model_id']
        _, agents = local_engine.validate_hosted_assessment(tid, ['gamma.gguf', 'alpha.gguf'])
        self.assertEqual([a['file'] for a in agents], ['alpha.gguf', 'gamma.gguf'])
        with self.assertRaisesRegex(ValueError, 'at least one juror'):
            local_engine.validate_hosted_assessment(tid, [])
        with self.assertRaisesRegex(ValueError, 'Unknown'):
            local_engine.validate_hosted_assessment(tid, ['missing.gguf'])
        with self.assertRaises(ValueError):
            local_engine.validate_hosted_assessment(tid, 'alpha.gguf')

    def test_single_agent_is_ready(self):
        self.write_agents(names=('solo.gguf',))
        with patch.object(local_engine, '_has_llama', return_value=True):
            status = local_engine.initialize_hosted_agents(preload=False)
        self.assertTrue(status['ready'])
        self.assertEqual(len(status['agents']), 1)
        self.assertEqual(status['agents'][0]['name'], 'solo.gguf')

    def test_live_rescan_picks_up_new_files(self):
        self.write_agents(names=('first.gguf',))
        with patch.object(local_engine, '_has_llama', return_value=True):
            status = local_engine.initialize_hosted_agents(preload=False)
            self.assertEqual(len(status['agents']), 1)
            (self.agents / 'second.gguf').write_bytes(b'GGUF' + b'\x02' * 16)
            refreshed = local_engine.hosted_status()
        self.assertTrue(refreshed['ready'])
        self.assertEqual([a['name'] for a in refreshed['agents']], ['first.gguf', 'second.gguf'])

    def test_no_scripted_substitute_and_distinct_weights(self):
        self.write_agents(duplicate=True)
        with patch.object(local_engine, '_has_llama', return_value=True):
            status = local_engine.initialize_hosted_agents(preload=False)
        self.assertFalse(status['ready'])
        self.assertIn('distinct', status['error'])

    def test_symlink_escape_rejected(self):
        outside = self.root / 'other.gguf'
        outside.write_bytes(b'GGUF' + b'\x01' * 16)
        link = self.agents / 'escaped.gguf'
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks unavailable on this system')
        status = local_engine.initialize_hosted_agents(preload=False)
        self.assertFalse(status['ready'])
        self.assertTrue(status['error'])

    def test_no_llama_dependency_is_reported_as_unavailable(self):
        self.write_agents()
        with patch.object(local_engine, '_has_llama', return_value=False):
            status = local_engine.initialize_hosted_agents(preload=True)
        self.assertFalse(status['ready'])
        self.assertFalse(status['preloaded'])
        self.assertIn('llama-cpp-python', status['error'])

    def test_frontend_only_requires_one_visitor_model_upload(self):
        root = Path(__file__).resolve().parents[1]
        html = (root / 'static/index.html').read_text(encoding='utf-8')
        js = (root / 'static/app.js').read_text(encoding='utf-8')
        self.assertEqual(html.count('type="file"'), 1)
        self.assertIn('id="model-file"', html)
        self.assertIn('id="hosted-agents"', html)
        self.assertNotIn('agent-1-model', html)
        self.assertNotIn('red_team_model_ids', js)
        self.assertIn('new IntersectionObserver(', js)
        self.assertIn('refreshHealth', js)
        self.assertIn('setInterval', js)
        self.assertIn('4 EVALUATION DOMAINS', html)
        self.assertIn('Courthouse Stress Test', html)
        self.assertNotIn('AEGIS LAB', html)
        self.assertNotIn('for(let n=1;n<=3;n++)', js)
        self.assertNotIn('config/agent_models.json', js)

    def test_variable_agent_count_in_orchestrator(self):
        import test_orchestrator
        fake = test_orchestrator.FakeThreeModelRuntime()
        models = ['alpha.gguf', 'beta.gguf']
        events = list(courthouse.assess_stream('target', 'target.gguf', 'sha', models, fake,
          lambda case: {'content': 'red blue', 'tool_calls': []}, rounds=2))
        report = events[-1]['report']
        self.assertEqual(len(report['agents']), 2)
        self.assertEqual(report['total'], 16)
        self.assertEqual(report['tested'], 16)
        for a in report['agents']:
            self.assertEqual(len(a['categories']), 4)
            self.assertEqual(a['tests'], 8)
        self.assertGreater(len(report['courthouse']['cross_agent_messages']), 0)

    def test_single_agent_orchestrator_skips_peer_exchange(self):
        import test_orchestrator
        fake = test_orchestrator.FakeThreeModelRuntime()
        events = list(courthouse.assess_stream('target', 'target.gguf', 'sha', ['solo.gguf'], fake,
          lambda case: {'content': 'red blue', 'tool_calls': []}, rounds=2))
        report = events[-1]['report']
        self.assertEqual(len(report['agents']), 1)
        self.assertEqual(report['total'], 8)
        peer_msgs = [m for m in report['courthouse']['cross_agent_messages'] if m['case'].startswith('PEER-')]
        self.assertEqual(peer_msgs, [])

    def test_all_three_real_model_calls_cover_four_categories(self):
        import test_orchestrator
        fake = test_orchestrator.FakeThreeModelRuntime()
        models = ['agent1.gguf', 'agent2.gguf', 'agent3.gguf']
        events = list(courthouse.assess_stream('target', 'target.gguf', 'sha', models, fake,
          lambda case: {'content': 'red blue', 'tool_calls': []}, rounds=2))
        report = events[-1]['report']
        self.assertEqual(len(report['agents']), 3)
        self.assertEqual(report['total'], 24)
        self.assertEqual(report['tested'], 24)
        for a in report['agents']:
            self.assertEqual(len(a['categories']), 4)
            self.assertEqual(a['tests'], 8)
        self.assertGreater(len(report['courthouse']['cross_agent_messages']), 0)

if __name__ == '__main__':
    unittest.main()
