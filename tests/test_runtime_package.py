"""Every local import, including deferred flow imports, must ship in the image."""
import ast
from pathlib import Path
import shlex


def test_dockerfile_includes_all_local_runtime_dependencies():
    root=Path(__file__).resolve().parents[1]
    local={p.stem:p for p in root.glob('*.py')}
    shipped=set()
    for line in (root/'Dockerfile').read_text().splitlines():
        parts=shlex.split(line)
        if parts and parts[0]=='COPY':
            shipped.update(Path(p).stem for p in parts[1:-1] if p.endswith('.py'))
    missing=[]
    for module in shipped:
        for node in ast.walk(ast.parse(local[module].read_text())):
            names=([node.module.split('.')[0]] if isinstance(node,ast.ImportFrom) and node.module else
                   [alias.name.split('.')[0] for alias in node.names] if isinstance(node,ast.Import) else [])
            missing.extend(f'{module} -> {name}' for name in names if name in local and name not in shipped)
    assert not missing, 'Runtime files missing from image: '+', '.join(missing)
