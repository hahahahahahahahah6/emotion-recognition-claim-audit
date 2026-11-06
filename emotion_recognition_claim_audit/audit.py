"""Deterministic documentation and Python-source auditing."""
import argparse
import ast
import json
import os
from pathlib import Path
import re
import sys

from .phrases import EMOTIONRECOGNITION, NOEMOTIONRECOGNITION, GENERIC_NAMES


def matches(text, phrases):
    found = []
    for phrase in sorted(phrases, key=len, reverse=True):
        start = 0
        while True:
            index = text.find(phrase, start)
            if index < 0:
                break
            found.append((index, phrase))
            text = text[:index] + ' ' * len(phrase) + text[index + len(phrase):]
            start = index + len(phrase)
    return text, sorted(found)


def prose(text):
    lines = []
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith('```'):
            fenced = not fenced
        elif not fenced:
            lines.append(line.replace('`', ''))
    return '\n'.join(lines).lower()


def evidence(source):
    tree = ast.parse(source)
    aliases = {}
    shadow = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split('.')[0]] = item.name if item.asname else item.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and node.module:
            for item in node.names:
                aliases[item.asname or item.name] = node.module + '.' + item.name

    def resolve(node):
        if isinstance(node, ast.Name):
            if node.id in shadow:
                return ''
            return aliases.get(node.id, '')
        if isinstance(node, ast.Attribute):
            base = resolve(node.value)
            return base + '.' + node.attr if base else ''
        return ''

    def constructor(node):
        if not isinstance(node, ast.Call):
            return ''
        name = resolve(node.func)
        parts = name.split('.')
        if len(parts) < 2:
            return ''
        if parts[-1] == 'FER' and 'fer' in '.'.join(parts[:-1]).lower():
            return 'fer'
        if parts[-1] in ('HumeClient', 'HumeBatchClient') and 'hume' in '.'.join(parts[:-1]).lower():
            return 'hume'
        return ''

    instances = {}
    shadowed_instances = set()
    assignments = [n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.AnnAssign))]
    for _ in range(len(assignments) + 1):
        for node in assignments:
            value = node.value
            kind = constructor(value) or (instances.get(value.id, '') if isinstance(value, ast.Name) else '')
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in shadow:
                shadowed_instances.update(t.id for t in targets if isinstance(t, ast.Name))
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in shadow and kind:
                    instances[target.id] = kind

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = resolve(node.func)
        kwargs = {kw.arg: kw.value for kw in node.keywords}
        if name == 'transformers.pipeline':
            model = kwargs.get('model')
            if node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == 'text-classification' and isinstance(model, ast.Constant) and isinstance(model.value, str) and 'emotion' in model.value.lower():
                return True
        if name == 'deepface.DeepFace.analyze':
            actions = kwargs.get('actions')
            if isinstance(actions, (ast.List, ast.Tuple, ast.Set)) and any(isinstance(x, ast.Constant) and isinstance(x.value, str) and x.value.lower() == 'emotion' for x in actions.elts):
                return True
        if isinstance(node.func, ast.Attribute):
            attrs = []
            base = node.func
            while isinstance(base, ast.Attribute):
                attrs.append(base.attr)
                base = base.value
            kind = constructor(base) or (instances.get(base.id, '') if isinstance(base, ast.Name) else '')
            if kind == 'fer' and node.func.attr == 'detect_emotions':
                return True
            if kind == 'hume' and 'expression_measurement' in attrs:
                return True
            # A FER method requires its paired constructor, even though its
            # spelling also occurs in the generic vocabulary.
            if node.func.attr in GENERIC_NAMES and node.func.attr not in shadow:
                if isinstance(base, ast.Name) and (base.id in shadow or base.id in shadowed_instances):
                    continue
                if node.func.attr == 'detect_emotions' and (isinstance(base, ast.Call) or (isinstance(base, ast.Name) and base.id not in instances)):
                    # Ordinary unrelated objects remain valid generic bases;
                    # a constructor call must still satisfy the FER route.
                    if isinstance(base, ast.Call) and resolve(base.func).endswith('.FER'):
                        continue
                return True
        elif isinstance(node.func, ast.Name) and name and name.split('.')[-1] in GENERIC_NAMES and node.func.id not in shadow and name.split('.')[-1] not in shadow:
            return True
    return False


def audit(repo, ignore=(), verbose=False):
    root = Path(repo)
    if not root.is_dir():
        raise OSError('repository is not a directory: ' + str(root))
    documents = []
    sources = []
    decisions = []
    for directory, dirs, files in os.walk(root, onerror=lambda error: (_ for _ in ()).throw(error)):
        dirs[:] = sorted(d for d in dirs if d not in ('.git', '__pycache__', '.venv', 'venv', 'env', '.env') and not (Path(directory) / d / 'pyvenv.cfg').exists())
        for filename in sorted(files):
            path = Path(directory) / filename
            rel = path.relative_to(root).as_posix()
            if any(rel.startswith(prefix) for prefix in ignore):
                decisions.append('ignored ' + rel)
                continue
            if path.suffix == '.py':
                sources.append((rel, path))
            if rel == 'README.md' or (path.suffix == '.md' and (rel.startswith('docs/') or 'tests' in Path(rel).parts[:-1])):
                documents.append((rel, path))
    has_evidence = False
    for rel, path in sources:
        try:
            present = evidence(path.read_text(encoding='utf-8'))
            has_evidence |= present
            decisions.append('source ' + rel + (': evidence' if present else ': no evidence'))
        except SyntaxError:
            decisions.append('source ' + rel + ': invalid Python; skipped')
    findings = []
    for rel, path in documents:
        clean, denials = matches(prose(path.read_text(encoding='utf-8')), NOEMOTIONRECOGNITION)
        _, claims = matches(clean, EMOTIONRECOGNITION)
        decisions.append('documentation ' + rel + ': ' + str(len(claims)) + ' claims, ' + str(len(denials)) + ' denials')
        selected = denials if has_evidence else claims
        for offset, phrase in selected:
            denial = has_evidence
            rule = 'documented-no-emotion-recognition-claim-false' if denial else 'documented-emotion-recognition-claim-false'
            severity = 'MEDIUM' if not denial and 'tests' in Path(rel).parts[:-1] else 'HIGH'
            findings.append(dict(rule_id=rule, severity=severity, path=rel, phrase=phrase, offset=offset, verdict='FAIL', message='Documented denial contradicts Python evidence.' if denial else 'Documented capability has no Python evidence.'))
    if verbose:
        print('Scope: README.md, docs/**/*.md, test Markdown fixtures; Python modules', file=sys.stderr)
        for decision in decisions:
            print(decision, file=sys.stderr)
    return findings


class Parser(argparse.ArgumentParser):
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, self.prog + ': error: ' + message + '\n')


def main(argv=None):
    parser = Parser(prog='emotion-recognition-claim-audit')
    parser.add_argument('--version', action='version', version='0.1.0')
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('audit')
    command.add_argument('repo', nargs='?', default='.')
    command.add_argument('--json', action='store_true')
    command.add_argument('--verbose', action='store_true')
    command.add_argument('--ignore', action='append', default=[])
    command.add_argument('--fail-on', choices=('high', 'medium'), default='high')
    args = parser.parse_args(argv)
    try:
        findings = audit(args.repo, args.ignore, args.verbose)
    except (OSError, UnicodeError) as error:
        print(str(error), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(findings, indent=2))
    elif findings:
        for finding in findings:
            print('{severity} {rule_id} {path}: {message}'.format(**finding))
    else:
        print('PASS')
    return 2 if any(f['severity'] == 'HIGH' or args.fail_on == 'medium' for f in findings) else 0
