"""Run only the EXE in a new folder with no Python/Conda paths or local config."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile

from guard.exitcheck import SCENARIOS


def isolated_environment(home):
    env={k:v for k,v in os.environ.items()
         if not k.upper().startswith(('CONDA','PYTHON','_PYI_','PYINSTALLER_'))
         and k.upper() not in ('VIRTUAL_ENV','TCL_LIBRARY','TK_LIBRARY','V2RAYN_SPLIT_GUARD_QT_RUNTIME')
         and not k.upper().startswith(('QT_','QML'))}
    windows=Path(env['SYSTEMROOT'])
    env['PATH']=os.pathsep.join(str(p) for p in (windows/'System32',windows,windows/'System32/WindowsPowerShell/v1.0'))
    for key,folder in (('LOCALAPPDATA','新用户数据'),('APPDATA','漫游数据'),('TEMP','临时文件'),('TMP','临时文件')):
        path=home/folder;path.mkdir(exist_ok=True)
        env[key]=str(path)
    env['PYINSTALLER_STRICT_UNPACK_MODE']='1'
    return env


def run(executable):
    results=[]
    with tempfile.TemporaryDirectory(prefix='split-guard-portable-') as tmp:
        home=Path(tmp)/'便携测试 空格';home.mkdir()
        target=home/'分流助手.exe'
        shutil.copy2(executable,target)
        assert len(list(home.iterdir()))==1
        env=isolated_environment(home)
        def launch(arguments,proof,timeout=35,extra_env=None):
            proc=subprocess.run([str(target),*arguments,'--output',str(proof)],cwd=home,env=dict(env,**(extra_env or {})),
                                stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout,
                                creationflags=subprocess.CREATE_NO_WINDOW)
            assert proc.returncode==0 and proof.is_file(), 'Portable launch failed: '+proc.stderr.decode('utf-8',errors='replace')[:1000]
            result=json.loads(proof.read_text(encoding='utf-8'))
            assert result['ok'], result
            return result
        runtime=launch(['--runtime-self-test'],home/'runtime.json')
        assert runtime['frozen'] and runtime['bundled_imports_only'] and runtime['bits']==64
        results.append(dict(scenario='isolated_runtime',result=runtime))
        for scenario in SCENARIOS:
            result=launch(['--exit-self-test',scenario],home/f'exit-{scenario}.json')
            assert result['real_tray'] and result['network_writes']==0
            results.append(result)
        for factor in ('1','1.25','1.5','1.75','2','2.5'):
            result=launch(['--qt-ui-test'],home/f'scale-{factor}.json',extra_env={'QT_SCALE_FACTOR':factor})
            assert abs(result['device_pixel_ratio']-float(factor))<0.01, result
            results.append(dict(scenario='scale_'+factor,result=result))
        # Intentional LGPL library replacement is separate from the default
        # isolated-runtime check above. No system environment or settings change.
        import PySide6
        replacement=Path(PySide6.__file__).resolve().parent.parent
        result=launch(['--ui-self-test','--qt-runtime',str(replacement)],home/'replacement.json')
        assert result['runtime_override_verified']
        results.append(dict(scenario='optional_runtime_replacement',result=result))
        # Exercise the real first-run entrypoint: missing v2rayN settings is a
        # diagnostic state, not a missing-Python crash. Read-only network queries.
        proc=subprocess.run([str(target),'--diagnose','--output',str(home/'diagnostic.json')],
                            cwd=home,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                            timeout=45,creationflags=subprocess.CREATE_NO_WINDOW)
        assert proc.returncode==0, 'First-run diagnostic failed'
        diagnostic=json.loads((home/'diagnostic.json').read_text(encoding='utf-8'))
        assert diagnostic['redacted'] and not diagnostic['node']['identified']
        assert not list((Path(env['LOCALAPPDATA'])/'V2rayNSplitGuard').glob('settings.json'))
        assert not list(Path(env['TEMP']).glob('_MEI*')), 'Temporary runtime was not cleaned up'
        results.append(dict(scenario='new_user_diagnostic',ok=True,redacted=True,
                            personal_settings_used=False,temporary_runtime_cleaned=True,network_writes=0))
    return results


if __name__=='__main__':
    import sys
    print(json.dumps(run(Path(sys.argv[1]).resolve()),ensure_ascii=False,indent=2))
