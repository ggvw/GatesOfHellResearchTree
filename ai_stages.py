"""Static extraction of conquest AI rosters. Never executes Lua or infers AI from research."""
import re


# Comments are masked, preserving strings and line numbers (including Lua long strings).
_LUA = re.compile(r'--\[(=*)\[.*?\]\1\]|--[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|\[(=*)\[.*?\]\2\]', re.S)


def mask_lua_comments(text):
    return _LUA.sub(lambda m: re.sub(r'[^\n]', ' ', m[0]) if m[0].startswith('--') else m[0], text)


# Strings are indivisible tokens in both table traversal and field extraction.
_LUA_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|\[(=*)\[.*?\]\1\]|[A-Za-z_][A-Za-z_0-9]*|[^\s]', re.S)


def lua_tables(text):
    """Yield balanced table bodies; all string forms are opaque."""
    stack = []
    for token in _LUA_TOKEN.finditer(text):
        if token[0] == '{':
            stack.append(token.start())
        elif token[0] == '}':
            if not stack:
                raise ValueError('unmatched Lua closing brace')
            start = stack.pop()
            yield start, text[start:token.end()]
    if stack:
        raise ValueError('unclosed Lua table')


def lua_literal(tokens):
    """Decode one complete literal, or reject dynamic/unsupported expressions."""
    if len(tokens) != 1:
        return None
    value = tokens[0]
    long = re.fullmatch(r'\[(=*)\[(.*?)\]\1\]', value, re.S)
    if long:
        # Lua ignores an initial newline in a long string.
        return re.sub(r'^\r?\n', '', long[2])
    if not re.fullmatch(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', value, re.S):
        return None
    content, result, i = value[1:-1], [], 0
    escapes = {'a': '\a', 'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t', 'v': '\v', '\\': '\\', '"': '"', "'": "'"}
    while i < len(content):
        char = content[i]
        i += 1
        if char != '\\':
            if char in '\r\n':
                return None
            result.append(char)
            continue
        if i == len(content):
            return None
        escape = content[i]
        i += 1
        if escape in escapes:
            result.append(escapes[escape])
        elif escape.isascii() and escape.isdigit():
            number = escape
            while i < len(content) and len(number) < 3 and content[i] in '0123456789':
                number += content[i]
                i += 1
            if int(number) > 255:
                return None
            result.append(chr(int(number)))
        elif escape == 'x' and re.fullmatch(r'[0-9a-fA-F]{2}', content[i:i+2]):
            result.append(chr(int(content[i:i+2], 16)))
            i += 2
        elif escape in '\r\n':
            if escape == '\r' and content[i:i+1] == '\n':
                i += 1
            result.append('\n')
        else:
            return None
    return ''.join(result)


def lua_fields(body):
    """Read actual direct key=value fields; never search inside string tokens."""
    fields, chunk, depth = {}, [], 0
    def finish():
        if len(chunk) >= 2 and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*', chunk[0]) and chunk[1] == '=':
            fields[chunk[0]] = chunk[2:]
        chunk.clear()
    for token in _LUA_TOKEN.finditer(body[1:-1]):
        value = token[0]
        if value in (',', ';') and depth == 0:
            finish()
            continue
        chunk.append(value)
        if value in ('{', '(', '['):
            depth += 1
        elif value in ('}', ')', ']'):
            depth -= 1
    finish()
    return fields


def parse_roster(text, source, warn):
    clean = mask_lua_comments(text)
    result = []
    for offset, body in lua_tables(clean):
        fields = lua_fields(body)
        if 'unit' not in fields:
            continue
        purchase = lua_literal(fields['unit'])
        line = clean.count('\n', 0, offset) + 1
        if purchase is None:
            warn(f'{source}:{line}: unsupported AI unit expression or string escape; raw record retained')
            purchase = f'unknown:{source}:{line}:{offset}'
        base = fields.get('base', [])
        labels = []
        if base[:1] == ['{'] and base[-1:] == ['}']:
            for token in base[1:-1]:
                if token not in (',', ';'):
                    label = lua_literal([token])
                    if label is not None:
                        labels.append(label)
        result.append({'purchase_id': purchase, 'category': ' / '.join(labels) or 'Unknown category',
                       'source': source, 'line': line, 'raw': body})
    return result


def extract_ai(data, faction):
    warnings = []
    def warn(message):
        warnings.append(message)
        data.warn(message)
    utility = 'script/multiplayer/modes/utility.lua'
    text = mask_lua_comments(data.text(utility)) if utility in data.files else ''
    # Support the inspected modular runtime, fail visibly for different loaders.
    required = ('MaxDivisionArmyCount', 'math.random(1, upperLimit)', '[[/script/multiplayer/units/]]')
    entry_path = 'script/multiplayer/bot.main.lua'
    mode_path = 'script/multiplayer/modes/conquest.lua'
    entry = mask_lua_comments(data.text(entry_path)) if entry_path in data.files else ''
    mode = mask_lua_comments(data.text(mode_path)) if mode_path in data.files else ''
    dispatch_supported = ('/script/multiplayer/modes/' in entry and
                          'OnGameStartUtility("conquest")' in mode and
                          '/script/multiplayer/modes/utility' in mode)
    if not dispatch_supported or not all(value in text for value in required):
        return {'records': [], 'variants': [], 'schedules': {}, 'warnings': ['AI runtime loader unsupported or absent; no reachable variants inferred.']}
    count_table = re.search(r'MaxDivisionArmyCount\s*=\s*\{\s*Faction\s*=\s*\{([^}]+)', text)
    if not count_table:
        warn('AI MaxDivisionArmyCount declaration unsupported; no variants inferred')
        count = 0
    else:
        counts = dict(re.findall(r'\["([^"\n]+)"\]\s*=\s*(\d+)', count_table[1]))
        count = int(counts.get(faction, 1))
    records = []
    variants = []
    for variant in range(1, count + 1):
        source = f'script/multiplayer/units/{faction}/conquest.{faction}.{variant}.lua'
        variants.append(variant)
        if source not in data.files:
            warn(f'{source}: runtime-selectable AI module missing; variant retained with empty roster')
            continue
        try:
            rows = parse_roster(data.text(source), source, warn)
        except ValueError as exc:
            warn(f'{source}: {exc}; AI parsing incomplete')
            rows = []
        if not rows:
            warn(f'{source}: no AI purchase records parsed')
        records.extend(dict(row, variant=variant) for row in rows)
    schedules = {}
    for source in sorted(data.files):
        if re.fullmatch(r'set/dynamic_campaign/duration_[^/]+\.set', source):
            body = re.sub(r';[^\n]*', '', data.text(source))
            match = re.search(r'\{ResearchStages\s+"([^"]*)"\s*\}', body)
            name = source.rsplit('duration_', 1)[1][:-4]
            if match:
                pairs = re.findall(r'(\d+):(\d+)', match[1])
                if ' '.join(f'{a}:{b}' for a,b in pairs) != ' '.join(match[1].split()):
                    warn(f'{source}: unsupported ResearchStages schedule; not interpreted')
                else:
                    schedules[name] = [{'games_played': int(a), 'stage': int(b)} for a,b in pairs]
            else:
                warn(f'{source}: ResearchStages absent or unsupported')
    return {'records': records, 'variants': variants, 'schedules': schedules, 'warnings': warnings,
            'loader': utility}


def sdl_definitions(text):
    """Collect balanced define bodies; comments must already be masked."""
    result = {}
    for match in re.finditer(r'\(define\s+"([^"\n]+)"', text):
        depth = 0
        for token in re.finditer(r'"(?:\\.|[^"\\])*"|[()]', text[match.start():]):
            if token[0] == '(':
                depth += 1
            elif token[0] == ')':
                depth -= 1
                if depth == 0:
                    result[match[1]] = text[match.end():match.start()+token.end()-1]
                    break
    return result


def expand_sdl(block, definitions, active=()):
    """Expand literal named calls and key(value) arguments, without evaluating SDL."""
    pattern = r'\("([^"\n]+)"((?:\s*\w+\([^()]*\))*)\s*\)'
    def invoke(match):
        name = match[1]
        if name not in definitions or name in active:
            return match[0]
        args = dict(re.findall(r'(\w+)\(([^()]*)\)', match[2]))
        body = re.sub(r'%(\w+)', lambda m: args.get(m[1], m[0]), definitions[name])
        return expand_sdl(body, definitions, (*active, name))
    return re.sub(pattern, invoke, block or '')


def emitted_purchase_id(block, definitions):
    expanded = expand_sdl(block, definitions)
    match = re.search(r'\{\s*"([^"\n]+)"', expanded)
    return match[1] if match and '%' not in match[1] else None


def add_purchase_alias(unit_blocks, block, definitions):
    """Add a macro-emitted lookup only when no exact record already owns its ID."""
    emitted = emitted_purchase_id(block, definitions)
    if emitted:
        unit_blocks.setdefault(emitted, block)


def stage_bound(block, field, definitions=None):
    """Resolve engine stage fields through templates; absent is not infinity."""
    engine_field = {'min_stage': 'research_stage', 'max_stage': 'research_stage_max'}[field]
    expanded = expand_sdl(block, definitions) if definitions is not None else (block or '')
    values = re.findall(r'\{\s*' + engine_field + r'\s+([^{}]+)\}', expanded)
    if values:
        raw = values[-1].strip()
        source = 'engine-field'
    else:
        # Without definitions this helper can inspect explicit argument syntax,
        # but export always supplies the effective templates.
        match = re.search(r'\b' + field + r'\(([^()]*)\)', block or '') if definitions is None else None
        if not match:
            return {'state': 'absent', 'value': None}
        raw, source = match[1].strip(), 'argument'
    return {'state': 'known' if re.fullmatch(r'\d+', raw) else 'unknown',
            'value': int(raw) if re.fullmatch(r'\d+', raw) else None, 'raw': raw, 'source': source}
