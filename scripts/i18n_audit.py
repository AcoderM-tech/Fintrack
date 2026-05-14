import pathlib
import re
import sys
from collections import defaultdict


def _iter_files(root: pathlib.Path, pattern: str):
    yield from root.rglob(pattern)


def _collect_template_t_keys(templates_root: pathlib.Path) -> set[str]:
    # Matches:
    #   {% t "Text" %}
    #   {% t 'Text' as var %}
    # Does not try to resolve: {% t variable %}
    rx = re.compile(r"{%\s*t\s+(['\"])(.*?)\1", re.S)
    keys: set[str] = set()
    for path in _iter_files(templates_root, "*.html"):
        try:
            txt = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in rx.finditer(txt):
            key = (m.group(2) or "").strip()
            if key:
                keys.add(key)
    return keys


def _collect_python_i18n_keys(code_root: pathlib.Path) -> set[str]:
    # Matches:
    #   _i18n_translate("Text", lang)
    #   _i18n_translate('Text', lang)
    # Does not try to resolve dynamic strings.
    rx = re.compile(r"_i18n_translate\s*\(\s*(['\"])(.*?)\1", re.S)
    keys: set[str] = set()
    for path in _iter_files(code_root, "*.py"):
        # Avoid self-matching the examples in this script.
        if path.resolve() == pathlib.Path(__file__).resolve():
            continue
        if any(part in {"migrations", "__pycache__"} for part in path.parts):
            continue
        try:
            txt = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for m in rx.finditer(txt):
            key = (m.group(2) or "").strip()
            if key:
                keys.add(key)
    return keys


def main() -> int:
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))

    try:
        from core.i18n import TRANSLATIONS  # type: ignore
    except Exception as e:
        print(f"Failed to import core.i18n.TRANSLATIONS: {e}", file=sys.stderr)
        return 2

    keys = set()
    keys |= _collect_template_t_keys(repo_root / "templates")
    keys |= _collect_python_i18n_keys(repo_root)

    print(f"Total i18n keys found (templates + python): {len(keys)}")

    missing_by_lang: dict[str, list[str]] = defaultdict(list)
    for lang in ("ru", "en"):
        lang_map = TRANSLATIONS.get(lang, {})
        for key in sorted(keys):
            if key not in lang_map:
                missing_by_lang[lang].append(key)

    for lang in ("ru", "en"):
        miss = missing_by_lang.get(lang, [])
        print(f"\nMissing in {lang}: {len(miss)}")
        for key in miss[:120]:
            print(f" - {key}")
        if len(miss) > 120:
            print(f" ... {len(miss) - 120} more")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
