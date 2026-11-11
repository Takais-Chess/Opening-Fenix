"""
Spell-checking highlighter and context menu integration for PyQt6 text widgets.
Provides underline formatting for misspelled words and right-click correction menus.
"""

from typing import Optional, Callable
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import (
    QSyntaxHighlighter,
    QTextCharFormat,
    QColor,
    QTextCursor,
    QAction,
    QFont
)
from PyQt6.QtWidgets import QPlainTextEdit, QTextEdit, QMenu

from opening_fenix.core.spellcheck_service import get_spellcheck_service, SpellCheckService
from opening_fenix.core.translation import tr_ui


class SpellCheckHighlighter(QSyntaxHighlighter):
    """
    Syntax highlighter that inspects words using SpellCheckService
    and marks unrecognized words with a red wavy underline.
    """

    def __init__(self, document, get_lang_fn: Optional[Callable[[], str]] = None):
        super().__init__(document)
        self.get_lang_fn = get_lang_fn
        self.service: SpellCheckService = get_spellcheck_service()

        self.error_format = QTextCharFormat()
        self.error_format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline)
        self.error_format.setUnderlineColor(QColor("#E53935")) # Vivid Red

        # Automatically refresh when dictionary or settings change
        self.service.register_listener(self.rehighlight)

    def current_language(self) -> str:
        if callable(self.get_lang_fn):
            try:
                lang = self.get_lang_fn()
                if lang:
                    return str(lang)
            except Exception:
                pass
        return "de"

    def highlightBlock(self, text: str):
        if not self.service.is_enabled():
            return

        lang = self.current_language()
        words_with_spans = self.service.extract_words_with_spans(text)

        for word, start, end in words_with_spans:
            if not self.service.is_word_valid(word, lang):
                self.setFormat(start, end - start, self.error_format)


def attach_spell_check(
    editor: QPlainTextEdit | QTextEdit,
    get_lang_fn: Optional[Callable[[], str]] = None
) -> SpellCheckHighlighter:
    """
    Attaches spell checking and custom right-click context menu to a QPlainTextEdit or QTextEdit.
    Returns the created SpellCheckHighlighter.
    """
    highlighter = SpellCheckHighlighter(editor.document(), get_lang_fn=get_lang_fn)
    editor._spell_highlighter = highlighter  # prevent GC

    # Unregister listener when widget is deleted to avoid leaks
    try:
        editor.destroyed.connect(lambda *_args: highlighter.service.unregister_listener(highlighter.rehighlight))
    except Exception:
        pass

    def custom_context_menu_event(event):
        svc = get_spellcheck_service()
        lang = highlighter.current_language()
        pos = event.pos()

        # Find word under cursor
        cursor = editor.cursorForPosition(pos)
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        selected_word = cursor.selectedText().strip("-_#*~`.,:;!?()[]{}'\"")

        menu: QMenu = editor.createStandardContextMenu()

        if svc.is_enabled() and selected_word and not svc.is_word_valid(selected_word, lang):
            # Misspelled word right-clicked: prepend suggestions and quick actions
            first_action = menu.actions()[0] if menu.actions() else None

            suggestions = svc.get_suggestions(selected_word, lang, limit=5)

            if suggestions:
                for sugg in reversed(suggestions):
                    action = QAction(sugg, menu)
                    # Bold font for suggestions
                    font = action.font()
                    font.setBold(True)
                    action.setFont(font)

                    def make_replace(replacement, crs):
                        def replace(*_args):
                            crs.beginEditBlock()
                            crs.insertText(replacement)
                            crs.endEditBlock()
                            highlighter.rehighlight()
                        return replace

                    action.triggered.connect(make_replace(sugg, cursor))
                    menu.insertAction(first_action, action)
            else:
                no_sugg_action = QAction(tr_ui("spellcheck.no_suggestions", "Keine Vorschläge"), menu)
                no_sugg_action.setEnabled(False)
                menu.insertAction(first_action, no_sugg_action)

            menu.insertSeparator(first_action)

            # Add to Dictionary action
            add_dict_action = QAction(
                tr_ui("spellcheck.add_to_dict", "„{word}“ zum Wörterbuch hinzufügen", word=selected_word),
                menu
            )
            def make_add_to_dict(w):
                def _add(*_args):
                    svc.add_to_user_dictionary(w)
                return _add
            add_dict_action.triggered.connect(make_add_to_dict(selected_word))
            menu.insertAction(first_action, add_dict_action)

            # Ignore word action
            ignore_action = QAction(
                tr_ui("spellcheck.ignore", "„{word}“ ignorieren", word=selected_word),
                menu
            )
            def make_ignore(w):
                def _ign(*_args):
                    svc.ignore_word(w)
                return _ign
            ignore_action.triggered.connect(make_ignore(selected_word))
            menu.insertAction(first_action, ignore_action)

            menu.insertSeparator(first_action)

        # Append Spell Check toggle at the bottom of the context menu
        menu.addSeparator()
        toggle_action = QAction(tr_ui("spellcheck.enabled", "Rechtschreibprüfung"), menu)
        toggle_action.setCheckable(True)
        toggle_action.setChecked(svc.is_enabled())

        def toggle_spellcheck(checked):
            svc.set_enabled(checked)
        toggle_action.toggled.connect(toggle_spellcheck)
        menu.addAction(toggle_action)

        menu.exec(event.globalPos())

    editor.contextMenuEvent = custom_context_menu_event
    return highlighter


class SpellCheckPlainTextEdit(QPlainTextEdit):
    """QPlainTextEdit subclass with spell checking pre-configured."""

    def __init__(self, parent=None, get_lang_fn: Optional[Callable[[], str]] = None):
        super().__init__(parent)
        self.highlighter = attach_spell_check(self, get_lang_fn=get_lang_fn)
