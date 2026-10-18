"""Release scanning must detect removed tokens without echoing their values."""
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('release_privacy',Path(__file__).resolve().parents[1]/'scripts/check_release_privacy.py')
scanner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


class ReleasePrivacyTests(unittest.TestCase):
    def test_removed_history_token_is_found_without_echo(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(scanner,'ROOT',Path(folder)):
            root=Path(folder)
            def git(*args):
                subprocess.run(['git',*args],cwd=root,check=True,capture_output=True)
            git('init')
            git('config','user.name','Scanner fixture')
            git('config','user.email','fixture@example.test')
            token='sk-'+'x'*36
            (root/'example.txt').write_text(token)
            git('add','example.txt')
            git('commit','-m','fixture one')
            (root/'example.txt').write_text('Public summary')
            git('add','example.txt')
            git('commit','-m','fixture two')
            self.assertEqual(scanner.scan()['findings'],[])
            result=scanner.scan(include_history=True)
            self.assertEqual([(r['scope'],r['rule']) for r in result['findings']],[('history','openai_style_key')])
            self.assertNotIn(token,json.dumps(result))

    def test_current_local_credential_in_notebook_output_is_found_without_echo(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(scanner,'ROOT',Path(folder)):
            root=Path(folder)
            subprocess.run(['git','init'],cwd=root,check=True,capture_output=True)
            value='fixture-'+'z'*32
            private_path='C:'+'/'+'Users'+'/'+'fixture-user'+'/'+'file'
            (root/'.env').write_text('SHOPAIKEY_API_KEY='+value)
            (root/'example.ipynb').write_text(json.dumps({'cells':[{'outputs':[{'output_type':'stream','text':[value,private_path]}]}]}))
            subprocess.run(['git','add','example.ipynb'],cwd=root,check=True,capture_output=True)
            result=scanner.scan()
            self.assertTrue(result['actual_local_value_comparison_performed'])
            self.assertTrue(any(r['rule']=='actual_local_credential' for r in result['findings']))
            self.assertTrue(any(r['rule']=='private_user_path' for r in result['findings']))
            self.assertNotIn(value,json.dumps(result))
            self.assertNotIn(private_path,json.dumps(result))


if __name__=='__main__':
    unittest.main()
