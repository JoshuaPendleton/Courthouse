"""Example attacks carry the real token; bad probes are skipped (attributed), never abort a trial."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import courthouse  # noqa: E402


def last_user_payload(messages):
    return json.loads(messages[-1]['content'])


class ExampleTokenTests(unittest.TestCase):
    def test_example_contains_assigned_token_and_copying_it_is_valid(self):
        seen = {}

        def copycat(model, messages, temperature, max_tokens, schema=None):
            payload = last_user_payload(messages)
            seen['example'] = payload['good_example_message_to_assistant']
            return json.dumps({'message_to_assistant': seen['example'], 'rationale': 'copied'})

        spec, attack, _ = courthouse.generate_attack(copycat, 'j', 'prompt_injection', 1, [], [])
        self.assertIn(spec['marker'], seen['example'])
        self.assertNotIn('OVERRIDE_EXAMPLE', seen['example'])
        self.assertNotIn('{TOKEN}', seen['example'])
        self.assertEqual(attack, seen['example'])


class SkipAttributionTests(unittest.TestCase):
    def run_quick(self, bad_model):
        def chat(model, messages, temperature, max_tokens, schema=None):
            if schema is courthouse.ATTACK_SCHEMA:
                if model == bad_model:
                    return '{"message_to_assistant": "too short", "rationale": ""}'
                payload = last_user_payload(messages)
                return json.dumps({'message_to_assistant': payload['good_example_message_to_assistant'],
                                   'rationale': 'r'})
            if schema is courthouse.INDIVIDUAL_SCHEMA:
                return json.dumps({'summary': 's', 'category_analysis': {k: 'a' for k, _ in courthouse.CATEGORIES}})
            return json.dumps({'message': 'm', 'summary': 's'})

        events = list(courthouse.assess_stream('t', 't.gguf', 'sha', ['good.gguf', 'bad.gguf'], chat,
                                               lambda case: {'content': 'red blue', 'tool_calls': []},
                                               mode='quick'))
        return events

    def test_quick_mode_continues_past_a_failing_juror(self):
        events = self.run_quick('bad.gguf')
        self.assertFalse([e for e in events if e['type'] == 'error'])
        report = events[-1]['report']
        self.assertEqual(report['total'], 8)
        self.assertEqual(len(report['results']), 8)
        bad = [r for r in report['results'] if r['agent_model'] == 'bad.gguf']
        self.assertTrue(all(r['status'] == 'skipped' and r['skip_cause'] == 'juror' for r in bad))
        self.assertTrue(all('bad.gguf' in r['reason'] for r in bad))
        good = [r for r in report['results'] if r['agent_model'] == 'good.gguf']
        self.assertTrue(all(r['status'] in ('pass', 'fail') and r['skip_cause'] is None for r in good))
        rel = {j['model']: j for j in report['juror_reliability']}
        self.assertEqual((rel['bad.gguf']['juror_failures'], rel['good.gguf']['juror_failures']), (4, 0))
        self.assertFalse(report['complete'])

    def test_target_failure_is_attributed_to_target(self):
        spec = courthouse.scenario('tool_use', 1)
        case = courthouse.Case('1-R1-tool_use', 'tool_use', spec['title'], spec['system'], 'x' * 40,
                               forbidden_tool=spec['forbidden_tool'], tools=spec['tools'])

        def broken(_case):
            raise RuntimeError('no tool template')

        r = courthouse.test_case(case, broken, 'A', 'j.gguf', 'r', 1)
        self.assertEqual((r['status'], r['skip_cause']), ('skipped', 'target'))


if __name__ == '__main__':
    unittest.main()
