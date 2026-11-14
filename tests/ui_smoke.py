import json
from pathlib import Path
from guard.qtcheck import smoke

if __name__=='__main__':
    result=smoke();Path('artifacts').mkdir(exist_ok=True)
    Path('artifacts/ui-smoke.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
