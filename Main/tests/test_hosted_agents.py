"""Cross-platform integration checks using synthetic GGUF headers, not a scripted red team."""
import io
import json
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
        self.config = self.root / 'agents.json'
        self.config.write_text(json.dumps({'agents': [
            {'name': f'Courthouse Agent {i}', 'file': f'agent{i}.gguf'} for i in (1, 2, 3)
        ]}))
        self.prev_dir = local_engine.DIR
        self.prev_hosted = local_engine.HOSTED_DIR
        self.prev_registry = local_engine.REGISTRY.copy()
        self.prev_agents = local_engine.HOSTED_AGENTS[:]
        self.prev_status = local_engine.HOSTED_STATUS.copy()
        local_engine.DIR = self.uploads
        local_engine.HOSTED_DIR = self.agents.resolve()
        local_engine.REGISTRY.clear()
        local_engine.HOSTED_AGENTS = []
        local_engine.HOSTED_STATUS = {'ready':False,'error':'not set'}
        local_engine._CACHE.clear()

    def tearDown(self):
        local_engine.DIR = self.prev_dir
        local_engine.HOSTED_DIR = self.prev_hosted
        local_engine.REGISTRY.clear()
        local_engine.REGISTRY.update(self.prev_registry)
        local_engine.HOSTED_AGENTS = self.prev_agents
        local_engine.HOSTED_STATUS = self.prev_status
        local_engine._CACHE.clear()
        self.temp.cleanup()

    def write_agents(self, duplicate=False):
        for n in (1,2,3):
            byte = 1 if (duplicate and n==3) else n
            (self.agents/f'agent{n}.gguf').write_bytes(b'GGUF'+bytes([byte])*16)

    def test_missing_hosted_weights_blocks_assessment(self):
        state = local_engine.initialize_hosted_agents(self.config,preload=False)
        self.assertFalse(state['ready'])
        self.assertIn('Missing',state['error'])
        with self.assertRaisesRegex(ValueError,'not ready'):
            local_engine.validate_hosted_assessment('unknown-target')

    def test_hosted_models_register_once_and_preload(self):
        self.write_agents()
        loaded=[]
        def load(model_id):
            loaded.append(model_id)
            return object()
        with patch.object(local_engine,'_has_llama',return_value=True), patch.object(local_engine,'_get_llm',side_effect=load):
            status=local_engine.initialize_hosted_agents(self.config,preload=True)
        self.assertTrue(status['ready'])
        self.assertTrue(status['preloaded'])
        self.assertEqual(loaded,['courthouse-agent-1','courthouse-agent-2','courthouse-agent-3'])
        self.assertEqual([m['model_id'] for m in local_engine.HOSTED_AGENTS],loaded)
        self.assertTrue(all(x['status']=='loaded' for x in status['agents']))
        target_bytes=b'GGUF'+b'Z'*16
        target=local_engine.save_upload(io.BytesIO(target_bytes),len(target_bytes),'target.gguf')
        actual,agents=local_engine.validate_hosted_assessment(target['model_id'])
        self.assertEqual(actual['name'],'target.gguf')
        self.assertEqual(len(agents),3)
        self.assertFalse(any(a['source']!='server_hosted' for a in agents))

    def test_no_scripted_substitute_and_distinct_weights(self):
        self.write_agents(duplicate=True)
        with patch.object(local_engine,'_has_llama',return_value=True):
            status=local_engine.initialize_hosted_agents(self.config,preload=False)
        self.assertFalse(status['ready'])
        self.assertIn('distinct',status['error'])

    def test_config_cannot_escape_agent_directory(self):
        self.config.write_text(json.dumps({'agents': [
            {'file':'../other.gguf'}, {'file':'agent2.gguf'}, {'file':'agent3.gguf'}
        ]}))
        status=local_engine.initialize_hosted_agents(self.config,preload=False)
        self.assertFalse(status['ready'])
        self.assertIn('inside models/agents',status['error'])

    def test_no_llama_dependency_is_reported_as_unavailable(self):
        self.write_agents()
        with patch.object(local_engine,'_has_llama',return_value=False):
            status=local_engine.initialize_hosted_agents(self.config,preload=True)
        self.assertFalse(status['ready'])
        self.assertFalse(status['preloaded'])
        self.assertIn('llama-cpp-python',status['error'])

    def test_frontend_only_requires_one_visitor_model_upload(self):
        root=Path(__file__).resolve().parents[1]
        html=(root/'static/index.html').read_text()
        js=(root/'static/app.js').read_text()
        self.assertEqual(html.count('type="file"'),1)
        self.assertIn('id="model-file"',html)
        self.assertIn('id="hosted-agents"',html)
        self.assertNotIn('agent-1-model',html)
        self.assertNotIn('red_team_model_ids',js)
        self.assertIn('new IntersectionObserver(',js)
        self.assertIn('4 EVALUATION DOMAINS',html)
        self.assertIn('Courthouse Stress Test',html)
        self.assertNotIn('AEGIS LAB',html)

    def test_all_three_real_model_calls_cover_four_categories(self):
        import test_orchestrator
        fake=test_orchestrator.FakeThreeModelRuntime()
        models=['Courthouse Agent 1: agent1.gguf','Courthouse Agent 2: agent2.gguf','Courthouse Agent 3: agent3.gguf']
        events=list(courthouse.assess_stream('target','target.gguf','sha',models,fake,
          lambda case: {'content':'red blue','tool_calls':[]},rounds=2))
        report=events[-1]['report']
        self.assertEqual(len(report['agents']),3)
        self.assertEqual(report['total'],24)
        self.assertEqual(report['tested'],24)
        for a in report['agents']:
            self.assertEqual(len(a['categories']),4)
            self.assertEqual(a['tests'],8)
        self.assertGreater(len(report['courthouse']['cross_agent_messages']),0)

if __name__=='__main__': unittest.main()
