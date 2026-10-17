"""Steam Workshop discovery and a read-only, layered game resource filesystem."""

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
import posixpath
import re
from zipfile import BadZipFile, ZipFile

APP_ID = '400750'


def warning(message):
    print(f'[game-data] WARNING: {message}', flush=True)


@dataclass(frozen=True)
class Mod:
    id: str
    name: str
    path: Path
    requires: tuple[str, ...] = ()
    deletes: tuple[str, ...] = ()

    def metadata(self):
        return {'id': self.id, 'name': self.name, 'path': str(self.path),
                'requires': list(self.requires), 'deletes': list(self.deletes)}


def discover_mods(resource_dir):
    """Find this game's Workshop content, including other registered Steam libraries."""
    libraries = set()
    for path in [Path(resource_dir).resolve(), Path.home() / '.local/share/Steam',
                 Path.home() / '.steam/steam']:
        for parent in (path, *path.parents):
            if parent.name == 'steamapps':
                libraries.add(parent)
                break
        if (path / 'steamapps').is_dir():
            libraries.add((path / 'steamapps').resolve())
    for library in list(libraries):
        config = library / 'libraryfolders.vdf'
        if config.is_file():
            try:
                for value in re.findall(r'"path"\s+"([^"]+)"', config.read_text(errors='replace')):
                    libraries.add(Path(value.replace('\\\\', '\\')) / 'steamapps')
            except OSError as exc:
                warning(f'Cannot read {config}: {exc}')
    mods = {}
    for library in sorted(libraries):
        content = library / 'workshop/content' / APP_ID
        if not content.is_dir():
            continue
        for folder in sorted(content.iterdir()):
            if not folder.is_dir() or not folder.name.isdigit():
                continue
            try:
                text = (folder / 'mod.info').read_text(encoding='utf-8-sig', errors='replace')
            except OSError as exc:
                warning(f'Unsupported Workshop folder {folder}: cannot read mod.info ({exc})')
                continue
            name = re.search(r'\{name\s+"([^"]+)"', text, re.I)
            if not (folder / 'resource').is_dir():
                warning(f'Unsupported mod structure: {folder} has no resource directory')
                continue
            requirements = [value for block in re.findall(r'\{require\s+([^}]+)\}', text, re.I)
                            for value in re.findall(r'"([^"]+)"', block)]
            if any(not re.fullmatch(r'(?:mod_)?\d+', value) for value in requirements):
                warning(f'Unsupported mod dependencies in {folder / "mod.info"}: {requirements}')
                continue
            mods[folder.name] = Mod(
                folder.name, re.sub(r'</?c(?:\([^)]*\))?>', '', name[1]).strip() if name else folder.name,
                folder, tuple(value.removeprefix('mod_') for value in requirements),
                tuple(re.findall(r'\{delete\s+"([^"]+)"', text, re.I)))
    return sorted(mods.values(), key=lambda mod: (mod.name.casefold(), mod.id))


def mod_layers(mod, mods):
    """Topologically order dependencies before the one selected mod; reject incomplete stacks."""
    by_id = {item.id: item for item in mods}
    result, active, done = [], set(), set()

    def visit(item):
        if item.id in active:
            raise ValueError(f'Cyclic mod dependency at {item.name} ({item.id})')
        if item.id in done:
            return
        active.add(item.id)
        for required in item.requires:
            if required not in by_id:
                raise ValueError(f'{item.name} requires missing Workshop mod {required}')
            visit(by_id[required])
        active.remove(item.id)
        done.add(item.id)
        result.append(item)
    visit(mod)
    return result


def normalize(name):
    return posixpath.normpath(str(name).replace('\\', '/')).lstrip('/').lower()


class ArchiveView:
    """ZipFile-shaped view, preserving the paths expected by the existing parsers."""
    def __init__(self, data, prefix=''):
        self.data, self.prefix = data, prefix

    def namelist(self):
        return [name[len(self.prefix):] for name in self.data.files if name.startswith(self.prefix)]

    def read(self, name):
        return self.data.read(self.prefix + str(name))

    def is_file(self):
        return True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def open_archive(source):
    return source if isinstance(source, ArchiveView) else ZipFile(source)


class GameData:
    """Base archives < dependencies < selected mod; sorted archives < loose files.

    Archives mount at their containing directory, as in the game. Only resource
    domains used by this viewer are indexed; maps, sounds and textures are skipped.
    """
    def __init__(self, resource_dir, layers=()):
        self.resource_dir = Path(resource_dir)
        self.layers = list(layers)
        self.files = {}
        self.stack = ExitStack()
        self.reported = set()
        self.text_cache = {}

    def warn(self, message):
        if message not in self.reported:
            self.reported.add(message)
            warning(message)

    def __enter__(self):
        try:
            self.mount(self.resource_dir)
            self.mount_localizations(self.resource_dir.parent)
            for mod in self.layers:
                if not (mod.path / 'resource').is_dir():
                    raise ValueError(f'Mod resource directory no longer exists: {mod.path}')
                for deleted in mod.deletes:
                    prefix = normalize(deleted).removeprefix('resource/').rstrip('/')
                    for name in list(self.files):
                        if name == prefix or name.startswith(prefix + '/'):
                            del self.files[name]
                self.mount(mod.path / 'resource')
                self.mount_localizations(mod.path)
            return self
        except Exception:
            self.stack.close()
            raise

    def __exit__(self, *args):
        return self.stack.__exit__(*args)

    @staticmethod
    def relevant(name):
        return name.startswith(('set/', 'properties/', 'entity/', 'interface/', 'localizations/'))

    def mount_archive(self, path, prefix):
        try:
            archive = self.stack.enter_context(ZipFile(path))
            for info in archive.infolist():
                if info.is_dir():
                    continue
                name = normalize(posixpath.join(prefix, info.filename.replace('\\', '/')))
                if self.relevant(name) and '/..' not in name:
                    self.files.pop(name, None)
                    self.files[name] = (archive, info.filename)
        except (OSError, BadZipFile, RuntimeError) as exc:
            self.warn(f'Cannot parse archive {path}: {exc}')

    def mount(self, root):
        # Nested archives contain paths relative to their parent, not their stem.
        paths = sorted(path for path in root.rglob('*') if path.is_file())
        for path in paths:
            if path.suffix.lower() != '.pak':
                continue
            relative = path.relative_to(root)
            if relative.parts[0].lower() in {'map', 'sound', 'texture', 'music', 'video'}:
                continue
            if relative.name.lower().startswith(('map.', 'sound ', 'music ', 'video ')):
                continue
            self.mount_archive(path, relative.parent.as_posix())
        for path in paths:
            if path.suffix.lower() != '.pak':
                name = normalize(path.relative_to(root).as_posix())
                if self.relevant(name):
                    self.files.pop(name, None)
                    self.files[name] = (None, path)

    def mount_localizations(self, root):
        directory = root / 'localizations'
        if not directory.is_dir():
            return
        # The viewer uses the default (English) localization, not other languages.
        for path in sorted(directory.iterdir()):
            if path.is_file() and path.name.lower().startswith('default') and path.suffix.lower() == '.pak':
                self.mount_archive(path, 'localizations')
        for path in sorted(directory.rglob('*')):
            if path.is_file() and path.suffix.lower() in {'.pot', '.po'}:
                name = 'localizations/' + normalize(path.relative_to(directory))
                self.files.pop(name, None)
                self.files[name] = (None, path)

    def view(self, prefix=''):
        return ArchiveView(self, prefix)

    def read(self, name):
        source, path = self.files[normalize(name)]
        try:
            return source.read(path) if source else path.read_bytes()
        except (OSError, BadZipFile, RuntimeError) as exc:
            self.warn(f'Cannot read {name}: {exc}')
            return b''

    def text(self, name, active=()):
        """Resolve relative text includes, reporting missing files and include cycles."""
        name = normalize(name)
        if not active and name in self.text_cache:
            return self.text_cache[name]
        if name in active:
            self.warn(f'Include cycle: {" -> ".join((*active, name))}')
            return ''
        if name not in self.files:
            self.warn(f'Missing reference: {name}')
            return ''
        text = self.read(name).decode('utf-8-sig', errors='replace')
        def include(match):
            if match[1] is None:
                return match[0]
            child = match[1]
            child = normalize(child.lstrip('/') if child.startswith('/') else
                              posixpath.join(posixpath.dirname(name), child))
            return self.text(child, (*active, name))
        result = re.sub(r';[^\r\n]*|\(include\s+"([^"]+)"\s*\)', include, text, flags=re.I)
        if not active:
            self.text_cache[name] = result
        return result


def expand_defines(text, report=warning):
    """Expand research/roster defines with key(value) arguments and integer +/- offsets."""
    text = re.sub(r';[^\r\n]*', lambda m: m[0] if re.match(r';\s*(?://)?---', m[0]) else '', text)
    definitions = {}
    pattern = re.compile(r'\(define\s+"([^"]+)"')

    def end_of_block(value, start):
        depth, quoted, escaped = 0, False, False
        for i in range(start, len(value)):
            char = value[i]
            if char == '"' and not escaped:
                quoted = not quoted
            if not quoted:
                depth += (char == '(') - (char == ')')
                if depth == 0:
                    return i + 1
            escaped = char == '\\' and not escaped
        return None

    while match := pattern.search(text):
        end = end_of_block(text, match.start())
        if end is None:
            report(f'Parsing error: unclosed define {match[1]}')
            text = text[:match.start()]
            break
        definitions[match[1]] = text[match.end():end - 1]
        text = text[:match.start()] + text[end:]
    for _ in range(30):
        changed = False
        def invoke(match):
            nonlocal changed
            if match[1] not in definitions:
                return match[0]
            changed = True
            args = dict(re.findall(r'(\w+)\(([^()]*)\)', match[2]))
            body = re.sub(r'%(\w+)', lambda m: args.get(m[1], m[0]), definitions[match[1]])
            return re.sub(r'\(([+-])\s+(-?\d+)\s+(-?\d+)\)',
                          lambda m: str(int(m[2]) + (1 if m[1] == '+' else -1) * int(m[3])), body)
        text = re.sub(r'\("([^"\n]+)"((?:\s+\w+\([^()]*\))*)\s*\)', invoke, text)
        if not changed:
            break
    else:
        report('Unsupported recursive or deeply nested defines')
    if re.search(r'%\w+|position\s+\(', text):
        report('Unsupported unresolved parameters or position expressions')
    return text
