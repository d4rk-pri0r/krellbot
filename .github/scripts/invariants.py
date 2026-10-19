"""Public static invariants. Read Git blobs and parse data; never execute candidates.

Run the trusted base copy with python -m scripts.invariants. The baseline is
an explicit issue-backed allowlist, not an automatic subtraction of base debt.
"""
from __future__ import annotations
import argparse
import ast
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path
import re
import sys
from . import _util

LLM_SDK_MODULES = frozenset({'openai', 'anthropic', 'litellm', 'google.generativeai', 'google.genai', 'cohere', 'mistralai', 'groq', 'ollama', 'langchain', 'langchain_openai', 'langchain_anthropic', 'llama_index', 'transformers'})
EXECUTION_ENTRY_POINTS = ('krellbot.cli', 'krellbot.api', 'krellbot.service', 'krellbot.run', 'krellbot.execution', 'krellbot.application.paper', 'krellbot.application.research', 'krellbot.application.rehearsal', 'krellbot.application.live_gate')
ARIA_MODIFIERS = frozenset({'Alt', 'Control', 'Shift', 'Meta', 'AltGraph'})
HEX_COLOR_RE = re.compile(r'#([0-9a-fA-F]{3,8})(?![\w-])')
VALID_HEX_LENGTHS = {3, 4, 6, 8}


@dataclass
class Finding:
    rule: str
    file: str
    line: int
    snippet: str
    detail: str
    identity: str = ''
    column: int = 1

    def __post_init__(self):
        if not self.identity:
            digest = hashlib.sha256(self.snippet.encode()).hexdigest()
            self.identity = f'{self.rule}|{self.file}|{self.line}|{self.column}|{digest}'


@dataclass
class RuleReport:
    rule: str
    shipped: bool
    reason: str
    findings: list[Finding] = field(default_factory=list)

    def to_dict(self):
        return {'rule': self.rule, 'shipped': self.shipped, 'reason': self.reason,
                'finding_count': len(self.findings), 'findings': [asdict(f) for f in self.findings]}


def module_name(path):
    value = path.removeprefix('src/').removesuffix('.py').replace('/', '.')
    return value.removesuffix('.__init__')


def relative_module(module, is_package, level, name):
    if not level:
        return name or ''
    parts = (module if is_package else module.rpartition('.')[0]).split('.')
    if level > len(parts):
        return None
    root = '.'.join(parts[:len(parts) - level + 1])
    return '.'.join(x for x in (root, name) if x)


def parsed_imports(text, module, is_package=False):
    """All syntactic imports, including lazy/conditional ones, with locations.

    Module reachability is conservative, not a dynamic Python call graph.
    Literal dynamic imports and aliases are resolved; computed ones are
    explicitly reported as unverifiable on reachable modules.
    """
    tree = ast.parse(text)
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                aliases[item.asname or item.name.split('.')[0]] = item.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == 'importlib':
            for item in node.names:
                aliases[item.asname or item.name] = 'importlib.' + item.name
    rows = []
    for node in ast.walk(tree):
        targets, uncertain = set(), None
        if isinstance(node, ast.Import):
            targets.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            root = relative_module(module, is_package, node.level, node.module)
            if root is None:
                uncertain = 'relative import escapes the known package'
            else:
                targets.add(root)
                targets.update(root + '.' + a.name for a in node.names if a.name != '*')
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name):
                name = aliases.get(fn.id, fn.id)
            elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                name = aliases.get(fn.value.id, fn.value.id) + '.' + fn.attr
            else:
                continue
            if name not in ('importlib.import_module', '__import__'):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                uncertain = 'computed dynamic import cannot be checked statically; use an explicit literal/module import'
            else:
                target = node.args[0].value
                if target.startswith('.'):
                    level = len(target) - len(target.lstrip('.'))
                    package_arg = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == 'package'), None)
                    if isinstance(package_arg, ast.Constant) and isinstance(package_arg.value, str):
                        package = package_arg.value
                    elif isinstance(package_arg, ast.Name) and package_arg.id == '__package__':
                        package = module if is_package else module.rpartition('.')[0]
                    else:
                        package = None
                    if package:
                        resolved = relative_module(package, True, level, target.lstrip('.'))
                        if resolved:
                            targets.add(resolved)
                        else:
                            uncertain = 'dynamic relative import escapes its package'
                    else:
                        uncertain = 'relative dynamic import has no statically known package'
                else:
                    targets.add(target)
        else:
            continue
        snippet = ast.get_source_segment(text, node) or text.splitlines()[node.lineno - 1]
        rows.append((node.lineno, node.col_offset + 1, snippet, targets, uncertain))
    return rows


def _scan_module_imports(text):
    """Small inspection helper; graph building supplies real package context."""
    static, dynamic, unresolved = set(), set(), []
    for line, _col, snippet, targets, uncertain in parsed_imports(text, 'example.module'):
        (dynamic if 'import_module(' in snippet or '__import__(' in snippet else static).update(targets)
        if uncertain or snippet.startswith('from .'):
            unresolved.append((line, snippet))
    return static, dynamic, unresolved


def import_analysis(git_src, ref, python_paths):
    paths = {module_name(p): p for p in python_paths if p.endswith('.py') and not p.startswith('.github/')}
    imports, graph, parse_errors = {}, {}, {}
    for name, path in paths.items():
        text = git_src.read_text(ref, path)
        if text is None:
            continue
        try:
            imports[name] = parsed_imports(text, name, path.endswith('/__init__.py'))
        except SyntaxError as exc:
            parse_errors[name] = (exc.lineno or 1, str(exc))
            imports[name] = []
        edges = set()
        for _line, _col, _snippet, targets, _unknown in imports[name]:
            for target in targets:
                # Python initializes parent packages too; never collapse to just the first component.
                for size in range(1, len(target.split('.')) + 1):
                    candidate = '.'.join(target.split('.')[:size])
                    if candidate in paths:
                        edges.add(candidate)
        graph[name] = edges
    return paths, imports, graph, parse_errors


def _bfs(adjacency, roots):
    seen, queue = set(), deque(roots)
    while queue:
        node = queue.popleft()
        if node not in seen:
            seen.add(node)
            queue.extend(adjacency.get(node, ()))
    return seen


def _build_import_graph(git_src, ref, python_paths):
    paths, _imports, graph, _errors = import_analysis(git_src, ref, python_paths)
    return graph, set(paths)


def rule_llm_sdk_imports(*, git_src, head_ref, python_paths, base_ref=None, refresh_audit=False):
    paths, imports, graph, errors = import_analysis(git_src, head_ref, python_paths)
    reached = _bfs(graph, EXECUTION_ENTRY_POINTS)
    findings = []
    for module in sorted(reached & paths.keys()):
        if module in errors:
            line, error = errors[module]
            findings.append(Finding('execution_import_unresolved', paths[module], line, error, 'Fix invalid syntax so the execution import graph can be checked.'))
        for line, col, snippet, targets, unknown in imports[module]:
            hits = sorted({sdk for target in targets for sdk in LLM_SDK_MODULES if target == sdk or target.startswith(sdk + '.')})
            if hits:
                findings.append(Finding('no_llm_sdk_imports', paths[module], line, snippet, f'LLM client import(s) {hits} reachable from execution entry points. Remove the client import from this path.', column=col))
            if unknown:
                findings.append(Finding('execution_import_unresolved', paths[module], line, snippet, unknown + '; resolve this import or obtain an issue-backed review.', column=col))
    return findings


def rule_float_on_money(**_kwargs):
    return [], ('NOT SHIPPED: import/source audit confirms Decimal accounting but also explicit float conversions for reporting. A reliable money-taint rule needs typed value-flow boundaries, not names or a blanket float ban. No heuristic money guarantee is advertised.')


def rule_venue_clients_outside_boundary(*, git_src, head_ref, python_paths, base_ref=None, diff_paths=None, refresh_audit=False):
    paths, imports, graph, _errors = import_analysis(git_src, head_ref, python_paths)
    # PaperVenue/protocol modules are not concrete remote clients themselves.
    # Their parent package initialization can still re-export real adapters;
    # those transitive import paths must remain visible to this check.
    clients = {m for m in paths if m.startswith('krellbot.venues.') and m not in ('krellbot.venues.base', 'krellbot.venues.paper')}
    findings = []
    for module, rows in imports.items():
        if not paths[module].startswith('src/krellbot/'):
            continue
        if module in ('krellbot.run', 'krellbot.execution', 'krellbot.venues') or module.startswith(('krellbot.run.', 'krellbot.execution.', 'krellbot.venues.')):
            continue
        for line, col, snippet, targets, _unknown in rows:
            venue_targets = {x for x in targets if x == 'krellbot.venues' or x.startswith('krellbot.venues.')}
            reached = set()
            for target in venue_targets:
                # Include exact module imports and a package re-export's initialization graph.
                candidate = target
                while candidate and candidate not in paths:
                    candidate = candidate.rpartition('.')[0]
                if candidate:
                    reached.update(_bfs(graph, (candidate,)))
                if target.startswith(('krellbot.venues.kraken', 'krellbot.venues.coinbase')):
                    reached.add(target.rsplit('.', 1)[0] if target.count('.') > 2 else target)
            remote = reached & clients
            if remote or any(t.startswith(('krellbot.venues.kraken', 'krellbot.venues.coinbase')) for t in targets):
                findings.append(Finding('venue_clients_outside_boundary', paths[module], line, snippet, 'Concrete exchange client import bypasses the run/execution boundary. Route the operation through that boundary; existing CLI construction/probe debt requires a specific issue-backed exception.', column=col))
    return findings, 'Shipped module-import boundary: run/execution own exchange-client access; venue internals may import each other. PaperVenue/protocol modules are not remote clients, but eager parent-package adapter re-exports still count. This is not a proof against Python reflection or escaped client objects.'


def mask_comments(text, js=True):
    """Mask comments while preserving offsets/newlines and quoted strings."""
    result = list(text)
    i, quote = 0, None
    while i < len(text):
        if quote:
            if text[i] == '\\':
                i += 2
                continue
            if text[i] == quote:
                quote = None
            i += 1
            continue
        if text[i] in '\"\'`':
            quote = text[i]
            i += 1
            continue
        if text.startswith('/*', i) or (js and text.startswith('//', i)):
            if text.startswith('/*', i):
                end = text.find('*/', i + 2)
                end = len(text) if end < 0 else end + 2
            else:
                end = text.find('\n', i + 2)
                end = len(text) if end < 0 else end
            for j in range(i, end):
                if result[j] != '\n':
                    result[j] = ' '
            i = end
        else:
            i += 1
    return ''.join(result)


def interesting(rel):
    return (rel.startswith(('frontend/src/', 'frontend/public/')) or rel == 'frontend/index.html') and rel.endswith(('.tsx', '.ts', '.jsx', '.js', '.css', '.svg', '.html')) and rel != 'frontend/src/styles/tokens.css' and '.test.' not in rel and '__snapshots__' not in rel.split('/')


def mask_var_fallbacks(text):
    masked = list(text)
    for match in re.finditer(r'\bvar\s*\(', text):
        depth, comma, quote = 1, None, None
        i = match.end()
        while i < len(text) and depth:
            ch = text[i]
            if quote:
                if ch == '\\':
                    i += 2
                    continue
                if ch == quote:
                    quote = None
            elif ch in '\"\'':
                quote = ch
            elif ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif ch == ',' and depth == 1 and comma is None:
                comma = i
            if depth == 0 and comma is not None:
                for j in range(comma + 1, i):
                    if masked[j] != '\n':
                        masked[j] = ' '
            i += 1
    return ''.join(masked)


def _scan_hex_in_file(text, rel):
    masked = mask_var_fallbacks(mask_comments(text, js=not rel.endswith(('.css', '.svg', '.html'))))
    findings = []
    for match in HEX_COLOR_RE.finditer(masked):
        if len(match.group(1)) not in VALID_HEX_LENGTHS:
            continue
        prefix = masked[:match.start()]
        if rel.endswith('.css'):
            # A selector ID is not a paint value. CSS declarations carry a colon after the last statement delimiter.
            segment = re.split(r'[{};]', prefix)[-1]
            if ':' not in segment:
                continue
        if re.search(r'(?:href\s*=\s*[\"\']|url\(\s*[\"\']?)$', prefix):
            continue  # SVG/CSS fragment reference, not a color.
        line = masked.count('\n', 0, match.start()) + 1
        column = match.start() - masked.rfind('\n', 0, match.start())
        snippet = masked.splitlines()[line - 1].strip()
        findings.append(Finding('ui_hex_colors', rel, line, snippet, 'Move the raw hex color to frontend/src/styles/tokens.css and use var(--token), or put it in an actual var() fallback.', column=column))
    return findings


def rule_ui_hex_colors(*, git_src, head_ref, base_ref=None, refresh_audit=False):
    return [f for path in git_src.list_paths(head_ref, prefix='frontend/') if interesting(path) for f in _scan_hex_in_file(git_src.read_text(head_ref, path) or '', path)], 'Shipped literal-color check; comments and fragment references excluded, only tokens.css and balanced var() fallback values exempt.'


def _extract_aria_keyshortcuts_strings(text):
    text = mask_comments(text)
    constants = {m.group(1): m.group(3) for m in re.finditer(r'\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*([\"\'`])(.*?)\2', text, re.S)}
    pattern = re.compile(r'aria-keyshortcuts[\"\']?\s*(?:=|:)\s*(?:([\"\'])(.*?)\1|\{\s*([\"\'`])(.*?)\3\s*\}|\{\s*([A-Za-z_$][\w$]*)\s*\}|\{([^}]*)\})', re.S)
    result = []
    for match in pattern.finditer(text):
        line = text.count('\n', 0, match.start()) + 1
        if match.group(1):
            value = match.group(2)
        elif match.group(3):
            value = match.group(4)
            value = re.sub(r'\$\{\s*([\w$]+)\s*\}', lambda m: constants.get(m.group(1), '<unresolved>'), value)
        elif match.group(5):
            value = constants.get(match.group(5), '<unresolved>')
        else:
            value = '<unresolved>'
        result.append((line, match.group(0), value))
    return result


def _scan_aria_in_file(text, rel):
    findings = []
    for line, snippet, value in _extract_aria_keyshortcuts_strings(text):
        invalid = sorted({tok for shortcut in value.split() for tok in shortcut.split('+')[:-1] if tok not in ARIA_MODIFIERS})
        if '<unresolved>' in value or '${' in value:
            findings.append(Finding('aria_keyshortcuts_unresolved', rel, line, snippet, 'The shortcut value is not statically known. Use explicit valid ARIA shortcut strings or request issue-backed review.'))
        elif invalid:
            findings.append(Finding('aria_keyshortcuts_modifiers', rel, line, snippet, f'Invalid modifier(s) {invalid}. Use only Alt, Control, Shift, Meta, AltGraph before the key.'))
    return findings


def rule_aria_keyshortcuts(*, git_src, head_ref, base_ref=None, refresh_audit=False):
    return [f for p in git_src.list_paths(head_ref, prefix='frontend/') if interesting(p) and p.endswith(('.tsx', '.ts', '.jsx', '.js', '.html')) for f in _scan_aria_in_file(git_src.read_text(head_ref, p) or '', p)]


def rule_no_new_verify_scripts(*, git_src, base_ref, head_ref, refresh_audit=False):
    return [Finding('no_new_verify_scripts', p, 1, p, 'Do not add new scripts/verify_*.py. Use maintained journeys; existing paths require individual issue #92 allowlist entries.') for p in git_src.list_paths(head_ref, prefix='scripts/') if re.fullmatch(r'scripts/verify_[^/]+\.py', p)]


def evaluate_rules(*, git_src, base_ref, head_ref, refresh_audit=False):
    paths = [p for p in git_src.list_paths(head_ref) if p.endswith('.py')]
    llm = rule_llm_sdk_imports(git_src=git_src, head_ref=head_ref, python_paths=paths)
    money, reason = rule_float_on_money()
    venues, venue_reason = rule_venue_clients_outside_boundary(git_src=git_src, head_ref=head_ref, python_paths=paths)
    colors, color_reason = rule_ui_hex_colors(git_src=git_src, head_ref=head_ref)
    return [RuleReport('no_llm_sdk_imports', True, 'AST module graph from CLI/API/run/service entry points; relative, aliased and literal dynamic imports resolved; reachable computed imports fail as unverifiable.', llm),
            RuleReport('no_float_on_money', False, reason, money), RuleReport('venue_clients_outside_boundary', True, venue_reason, venues),
            RuleReport('ui_hex_colors', True, color_reason, colors), RuleReport('aria_keyshortcuts_modifiers', True, 'Static ARIA values, including named string constants; unresolved expressions require review.', rule_aria_keyshortcuts(git_src=git_src, head_ref=head_ref)),
            RuleReport('no_new_verify_scripts', True, 'Exact issue-backed path allowlist, not whatever happens to be on the PR base.', rule_no_new_verify_scripts(git_src=git_src, base_ref=base_ref, head_ref=head_ref))]


def filter_against_allowlist(reports, allowlist):
    # Locations remain precise audit evidence, not the permission identity.
    # Consume exact source occurrences so inserted lines do not reclassify old
    # debt, while a changed snippet or extra duplicate still fails the lint.
    available = Counter((entry['rule'], entry['file'], entry.get('column'), entry['snippet'])
                        for entry in allowlist.values())
    for report in reports:
        keep = []
        for finding in report.findings:
            entry = allowlist.get(finding.identity)
            if entry:
                assert all(entry.get(k) == getattr(finding, k) for k in ('rule', 'file', 'line', 'snippet')), 'Allowlist identity/evidence mismatch'
            evidence = (finding.rule, finding.file, finding.column, finding.snippet)
            if entry and 'column' not in entry:
                # Legacy fixture/schema entries still match their exact full
                # identity. They cannot acquire a column-wildcard exception.
                evidence = (finding.rule, finding.file, None, finding.snippet)
            if available[evidence] > 0:
                available[evidence] -= 1
            else:
                keep.append(finding)
        report.findings = keep
    return reports


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', required=True)
    p.add_argument('--head', required=True)
    p.add_argument('--workdir', default='.')
    p.add_argument('--allowlist', help='Explicit trusted base copy; CI must never load a candidate allowlist when one exists on base')
    p.add_argument('--refresh-audit', action='store_true', help='Report full candidate findings without automatically approving exceptions')
    p.add_argument('--json')
    args = p.parse_args(argv)
    try:
        source = _util.GitSource(Path(args.workdir))
        base, head = source.resolve(args.base), source.resolve(args.head)
        allowlist, origin = _util.load_trusted_allowlist(source.workdir, base, args.allowlist)
        reports = evaluate_rules(git_src=source, base_ref=base, head_ref=head)
        raw = [f for r in reports for f in r.findings]
        raw_counts = dict(Counter(f.rule for f in raw))
        reports = filter_against_allowlist(reports, allowlist)
        paths = [p for p in source.list_paths(head) if p.endswith('.py')]
        modules, _imports, graph, errors = import_analysis(source, head, paths)
        reached = sorted(_bfs(graph, EXECUTION_ENTRY_POINTS) & modules.keys())
        findings = [f for r in reports for f in r.findings]
        payload = {'base': base, 'head': head, 'allowlist_source': origin, 'allowlist_entry_count': len(allowlist),
                   'rules': [r.to_dict() for r in reports], 'raw_counts': raw_counts,
                   'import_graph': {'roots': [r for r in EXECUTION_ENTRY_POINTS if r in modules], 'reachable_modules': reached, 'module_count': len(modules), 'edges': {k: sorted(v) for k, v in graph.items() if k in reached}, 'parse_errors': errors},
                   'summary': {'shipped_rules': sum(r.shipped for r in reports), 'unshipped_rules': sum(not r.shipped for r in reports), 'total_findings_after_allowlist': len(findings)}}
        _util.write_json_if_requested(args.json, payload)
        for f in findings:
            print(f'{f.file}:{f.line}:{f.column}: {f.rule}: {f.detail} [{f.snippet}]')
        print(json.dumps({'raw_counts': raw_counts, 'summary': payload['summary']}))
        return int(bool(findings))
    except (ValueError, RuntimeError, OSError, AssertionError, KeyError) as exc:
        print(f'invariants:1: input-or-allowlist-error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
