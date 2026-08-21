$ErrorActionPreference = 'Stop'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONPATH = (
    (Resolve-Path '.venv\Lib\site-packages').Path + ';' +
    (Resolve-Path 'design\e6_final_exterior\step_anchored_v2\class_a_cad').Path + ';' +
    (Resolve-Path '.').Path
)

& 'C:\Users\86135\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' `
    -B -m unittest tests.test_v8_table_lid_packaging -v

exit $LASTEXITCODE
