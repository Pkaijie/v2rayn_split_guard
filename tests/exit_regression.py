"""Use a process deadline; a half-destroyed window must fail the test."""
import json
from pathlib import Path
import subprocess
import sys
from guard.exitcheck import SCENARIOS


def run(executable=None):
    output=Path('artifacts');output.mkdir(exist_ok=True)
    results=[]
    for scenario in SCENARIOS:
        proof=(output/f'exit-{scenario}.json').resolve()
        proof.unlink(missing_ok=True)
        args=[str(executable)] if executable else [sys.executable,'app.py']
        args+=['--exit-self-test',scenario,'--output',str(proof)]
        try:
            child=subprocess.run(args,timeout=12,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise AssertionError(f'{scenario}: 进程未在 12 秒内退出')
        if child.returncode or not proof.exists():
            raise AssertionError(f'{scenario}: 退出码 {child.returncode}，未正常完成')
        result=json.loads(proof.read_text(encoding='utf-8'))
        if not result['ok']:raise AssertionError(result)
        results.append(result)
    return results


if __name__=='__main__':
    print(json.dumps(run(sys.argv[1] if len(sys.argv)>1 else None),ensure_ascii=False,indent=2))
