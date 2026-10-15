"""Configurable fixed-menu knowledge-base client.

Answers stay in source documents. This module handles menu navigation,
deterministic document selection, and display without model rewriting.
"""

import argparse
import json
import re
import time
from pathlib import Path

from langchain_chroma import Chroma

from langchain_core.documents import Document

from langchain_ollama import OllamaEmbeddings

SCRIPT_REVISION = "2026-10-13-public-demo-config-v1"

DB_DIR = None

COLLECTIONS = {}

LANGUAGE_NAMES = {}

TOPIC_CONFIG = {}

TOPIC_MENU_OPTIONS = {}

TAX_TYPE_OPTION_LABELS = {}

EMBEDDING_MODEL = "nomic-embed-text"

EXIT_COMMANDS = {'quit', 'exit', 'q'}

MENU_REPLAY_CHOICES = []

MENU_SELECTION_HISTORY = []

class ExitRequested(Exception):
    """Signal that the user wants to leave during clarification."""

class PreviousMenuRequested(Exception):
    """Cancel this menu and reopen its immediate parent."""

class FixedMenuAnswerError(ValueError):
    """A selected source exists but cannot be rendered safely."""

STANDARD_ANSWER_TITLE = ""

STANDARD_ANSWER_HEADINGS = {}


def load_config(config_path):
    """Load and validate the public menu configuration."""

    path = Path(config_path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if data.get("schema") != 1:
        raise ValueError("Unsupported config schema; expected schema 1.")

    required = {
        "collections",
        "language_names",
        "topic_config",
        "topic_menu_options",
        "tax_type_option_labels",
        "standard_answer_title",
        "standard_answer_headings",
    }
    missing = sorted(required - data.keys())
    if missing:
        raise ValueError("Config is missing: " + ", ".join(missing))

    topics = data["topic_config"]
    for option_key, option in data["topic_menu_options"].items():
        topic_name = option.get("topic_name")
        if topic_name not in topics:
            raise ValueError(
                f"Menu option {option_key} references unknown topic {topic_name!r}."
            )

    return data


def configure(config_path, db_dir):
    """Apply one menu configuration and database location."""

    global COLLECTIONS
    global DB_DIR
    global EMBEDDING_MODEL
    global LANGUAGE_NAMES
    global STANDARD_ANSWER_HEADINGS
    global STANDARD_ANSWER_TITLE
    global TAX_TYPE_OPTION_LABELS
    global TOPIC_CONFIG
    global TOPIC_MENU_OPTIONS

    config = load_config(config_path)
    DB_DIR = str(Path(db_dir))
    COLLECTIONS = config["collections"]
    LANGUAGE_NAMES = config["language_names"]
    TOPIC_CONFIG = config["topic_config"]
    TOPIC_MENU_OPTIONS = config["topic_menu_options"]
    TAX_TYPE_OPTION_LABELS = config["tax_type_option_labels"]
    STANDARD_ANSWER_TITLE = config["standard_answer_title"]
    STANDARD_ANSWER_HEADINGS = config["standard_answer_headings"]
    EMBEDDING_MODEL = config.get("embedding_model", "nomic-embed-text")

def read_clarification_choice(question_text, valid_options, allow_back=True):
    """Read a valid terminal choice or propagate an exit command."""

    valid_options = list(valid_options)
    back_key = str(max(int(key) for key in valid_options) + 1) if allow_back else None
    if allow_back:
        question_text += "\n" + back_key + ". 回到上一级菜单"
        valid_options.append(back_key)

    if MENU_REPLAY_CHOICES:
        choice = MENU_REPLAY_CHOICES.pop(0)
        if choice in valid_options:
            MENU_SELECTION_HISTORY.append(choice)
            return choice
        MENU_REPLAY_CHOICES.clear()

    while True:
        print("\n" + question_text)
        choice = input("Selection: ").strip().lower()

        if choice in EXIT_COMMANDS:
            raise ExitRequested

        if allow_back and choice == back_key:
            MENU_REPLAY_CHOICES[:] = MENU_SELECTION_HISTORY[:-1]
            raise PreviousMenuRequested

        if choice in valid_options:
            MENU_SELECTION_HISTORY.append(choice)
            return choice

        print(
            "输入无效，请输入："
            + "、".join(valid_options)
            + "。"
        )

def ask_for_topic():
    """Let the user select one configured knowledge-base topic."""

    question_lines = ["请选择查询主题："]

    for option_key, option_config in TOPIC_MENU_OPTIONS.items():
        question_lines.append(
            option_key
            + ". "
            + option_config["label"]
        )

    choice = read_clarification_choice(
        question_text="\n".join(question_lines),
        valid_options=list(TOPIC_MENU_OPTIONS.keys()),
        allow_back=False,
    )
    return TOPIC_MENU_OPTIONS[choice]["topic_name"]

def ask_to_continue():
    """Choose the previous menu, the main menu, or exit."""

    while True:
        choice = input(
            "\n请选择下一步：\n"
            "1. 回到上一级菜单\n"
            "2. 回到主菜单\n"
            "3. 退出\n"
            "Selection: "
        ).strip().lower()

        if choice == "1":
            MENU_REPLAY_CHOICES[:] = MENU_SELECTION_HISTORY[:-1]
            return True

        if choice == "2":
            MENU_REPLAY_CHOICES.clear()
            return True

        if choice == "3" or choice in EXIT_COMMANDS:
            return False

        print("输入无效，请输入 1、2 或 3。")

def ask_for_scenario(topic_name):
    """Ask the topic-specific scenario question."""

    config = TOPIC_CONFIG[topic_name]

    askable_options = [
        scenario_key
        for scenario_key, scenario_config
        in config["scenarios"].items()
        if scenario_config.get("askable", True)
    ]

    return read_clarification_choice(
        question_text=config["scenario_question"],
        valid_options=askable_options,
    )

def resolve_scenario_config(
    topic_name,
    scenario_key,
    selected_tax_types=None,
):
    """Resolve optional nested and relief questions for a scenario."""

    topic_config = TOPIC_CONFIG[topic_name]
    base_config = topic_config["scenarios"][scenario_key]
    resolved_config = dict(base_config)
    labels = [base_config["label"]]

    selected_tax_types = set(selected_tax_types or [])
    subscenarios = base_config.get("subscenarios")
    subscenario_tax_types = set(
        base_config.get("subscenario_tax_types", [])
    )

    if (
        subscenarios
        and subscenario_tax_types
        and selected_tax_types.isdisjoint(
            subscenario_tax_types
        )
    ):
        subscenarios = None

    while subscenarios:
        subscenario_key = read_clarification_choice(
            question_text=resolved_config["subscenario_question"],
            valid_options=list(subscenarios),
        )

        subscenario_config = subscenarios[subscenario_key]
        resolved_config.update(subscenario_config)
        labels.append(subscenario_config["label"])
        subscenarios = subscenario_config.get("subscenarios")

    if (
        resolved_config.get("needs_relief_question")
        and "Withholding" in selected_tax_types
    ):
        relief_scenarios = resolved_config.get("relief_scenarios", topic_config.get(
            "relief_scenarios",
            {},
        ))
        relief_key = read_clarification_choice(
            question_text=resolved_config.get("relief_question", topic_config["relief_question"]),
            valid_options=list(relief_scenarios),
        )
        relief_config = relief_scenarios[relief_key]
        resolved_config.update(relief_config)
        labels.append(relief_config["label"])

    resolved_config["label"] = "；".join(labels)
    return resolved_config

def ask_for_tax_type(available_tax_types):
    """Ask only for tax types supported by the selected scenario."""

    option_map = {}
    question_lines = ["您要查询哪个税种？"]

    for index, tax_type in enumerate(
        available_tax_types,
        start=1,
    ):
        option_key = str(index)
        option_map[option_key] = tax_type
        question_lines.append(
            option_key
            + ". "
            + TAX_TYPE_OPTION_LABELS.get(
                tax_type,
                tax_type,
            )
        )

    choice = read_clarification_choice(
        question_text="\n".join(question_lines),
        valid_options=list(option_map.keys()),
    )
    return option_map[choice]

def get_vector_store(language, embeddings):
    """Open the collection for the selected language."""

    return Chroma(
        persist_directory=DB_DIR,
        collection_name=COLLECTIONS[language],
        embedding_function=embeddings,
    )

def metadata_matches_source(metadata, source_name):
    """Match either the source field or the basename of path."""

    metadata_source = str(
        metadata.get("source", "")
    ).replace("\\", "/")
    metadata_path = str(
        metadata.get("path", "")
    ).replace("\\", "/")

    return (
        metadata_source == source_name
        or metadata_path == source_name
        or metadata_path.endswith("/" + source_name)
    )

def get_configured_source_chunks(vectorstore, source_name):
    """
    Read one configured source without assuming its stored path.

    New databases normally match the source field directly. The
    full-collection fallback also supports older databases that
    identify the file only through path metadata.
    """

    data = vectorstore.get(
        where={"source": source_name},
        include=["documents", "metadatas"],
    )

    documents = data.get("documents") or []
    metadatas = data.get("metadatas") or []

    if not documents:
        data = vectorstore.get(
            include=["documents", "metadatas"],
        )
        documents = data.get("documents") or []
        metadatas = data.get("metadatas") or []

    source_chunks = []

    for content, metadata in zip(documents, metadatas):
        metadata = metadata or {}

        if not content or not content.strip():
            continue

        if not metadata_matches_source(
            metadata,
            source_name,
        ):
            continue

        source_chunks.append(
            Document(
                page_content=content,
                metadata=metadata,
            )
        )

    return sorted(
        source_chunks,
        key=lambda doc: doc.metadata.get(
            "chunk_index",
            0,
        ),
    )

def print_selected_context(docs, mode):
    """Print the chunks selected for answer construction."""

    print(f"\nSelected context mode: {mode}")
    print(
        f"Selected {len(docs)} chunk(s) "
        "for answer construction:"
    )

    for i, doc in enumerate(docs, start=1):
        source = doc.metadata.get(
            "source",
            "unknown source",
        )
        tax_type = doc.metadata.get(
            "tax_type",
            "General",
        )
        chunk_index = doc.metadata.get(
            "chunk_index",
            "unknown",
        )
        headings = [
            doc.metadata.get("heading_2", ""),
            doc.metadata.get("heading_3", ""),
            doc.metadata.get("heading_4", ""),
        ]
        section = " > ".join(
            heading
            for heading in headings
            if heading
        )

        print(
            f"  {i}. Source: {source} | "
            f"Tax type: {tax_type} | "
            f"Chunk index: {chunk_index} | "
            f"Section: {section or 'unknown'}"
        )

def clean_knowledge_base_chunk(content, tax_type):
    """Remove metadata labels added by the ingestion pipeline."""

    del tax_type

    metadata_prefixes = (
        "税种：",
        "税种:",
        "文档标题：",
        "文档标题:",
        "章节：",
        "章节:",
        "Tax type:",
        "Document title:",
        "Section:",
    )
    lines = content.strip().splitlines()

    while lines and (
        not lines[0].strip()
        or lines[0].strip().startswith(metadata_prefixes)
    ):
        lines.pop(0)

    while lines and not lines[0].strip():
        lines.pop(0)

    return "\n".join(lines).strip()

def get_chunk_section_identity(doc):
    """Return the metadata fields that identify one source section."""

    return (
        doc.metadata.get("path", ""),
        doc.metadata.get("title", ""),
        doc.metadata.get("heading_2", ""),
        doc.metadata.get("heading_3", ""),
        doc.metadata.get("heading_4", ""),
    )

def get_consecutive_chunk_index(previous_doc, current_doc):
    """Check whether two documents are consecutive source chunks."""

    try:
        previous_index = int(
            previous_doc.metadata.get("chunk_index")
        )
        current_index = int(
            current_doc.metadata.get("chunk_index")
        )
    except (TypeError, ValueError):
        return False

    return current_index == previous_index + 1

def find_line_overlap(previous_lines, current_lines):
    """Return the longest exact suffix/prefix overlap in lines."""

    max_overlap = min(
        len(previous_lines),
        len(current_lines),
    )

    for size in range(max_overlap, 0, -1):
        previous_part = [
            line.strip()
            for line in previous_lines[-size:]
        ]
        current_part = [
            line.strip()
            for line in current_lines[:size]
        ]
        overlap_text = "\n".join(current_part).strip()

        # Avoid treating a short heading, bullet or blank line as
        # an overlap between two chunks.
        if len(overlap_text) < 40:
            continue

        if previous_part == current_part:
            return size

    return 0

def merge_structured_chunk_contents(docs, tax_type):
    """Clean chunks and remove overlap only within one section."""

    merged_lines = []
    previous_doc = None
    previous_lines = []

    for doc in docs:
        content = clean_knowledge_base_chunk(
            content=doc.page_content,
            tax_type=tax_type,
        )

        if not content:
            continue

        current_lines = content.splitlines()
        overlap_size = 0

        if (
            previous_doc is not None
            and get_chunk_section_identity(previous_doc)
            == get_chunk_section_identity(doc)
            and get_consecutive_chunk_index(
                previous_doc,
                doc,
            )
        ):
            overlap_size = find_line_overlap(
                previous_lines,
                current_lines,
            )

        remaining_lines = current_lines[overlap_size:]

        if remaining_lines:
            if (
                overlap_size == 0
                and merged_lines
                and merged_lines[-1].strip()
            ):
                merged_lines.append("")

            merged_lines.extend(remaining_lines)

        previous_doc = doc
        previous_lines = current_lines

    return "\n".join(merged_lines).strip()

def render_document_sections(docs, tax_type, keep_headings=False):
    """Remove embedding labels and presentation prefixes, not conditions."""

    content = merge_structured_chunk_contents(docs, tax_type)
    lines = []
    for line in content.splitlines():
        if not keep_headings and line.lstrip().startswith("#"):
            continue
        if re.fullmatch(r"[-*_ ]{3,}", line.strip()):
            continue
        line = re.sub(r"^([ \t]*)税务处理[：:][ \t]*", r"\1", line)
        lines.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()

def get_menu_standard_answer_chunks(vectorstore, topic_name, scenario_config, tax_type):
    """Read exactly one source/scenario/tax answer, with no similarity fallback."""
    config = TOPIC_CONFIG[topic_name]
    names = [scenario_config.get("source", config["source"])]
    names.extend(scenario_config.get("source_aliases", config.get("source_aliases", [])))
    source_docs = []
    for name in dict.fromkeys(names):
        source_docs.extend(get_configured_source_chunks(vectorstore, name))
    if not source_docs:
        return []
    registry = [doc for doc in source_docs
                if doc.metadata.get("title") == STANDARD_ANSWER_TITLE]
    if not registry:
        raise FixedMenuAnswerError(
            "所选文档尚未入库统一标准答案。请替换对应文档并运行 python ingest.py；"
            "若仍报错，请核对文档及数据库路径。"
        )
    scene = "场景：" + scenario_config["label"]
    heading = STANDARD_ANSWER_HEADINGS[tax_type]
    selected = [doc for doc in registry
                if doc.metadata.get("heading_2") == scene
                and doc.metadata.get("heading_3") == heading
                and not doc.metadata.get("heading_4")]
    if not selected:
        raise FixedMenuAnswerError(
            "标准答案章节未匹配：" + scenario_config["label"] + " / " + tax_type
            + "。请核对场景标题、税种及入库结果；不会改用其他段落。"
        )
    if any(doc.metadata.get("tax_type") != tax_type for doc in selected):
        raise FixedMenuAnswerError("标准答案税种标记不匹配；请检查文档标题与入库结果。")
    paths = {doc.metadata.get("path", doc.metadata.get("source")) for doc in selected}
    header_count = sum(len(re.findall(r"(?m)^###\s+" + re.escape(heading) + r"\s*$",
                                     doc.page_content)) for doc in selected)
    if len(paths) != 1 or header_count != 1:
        raise FixedMenuAnswerError("标准答案重复或章节结构异常；请检查 docs 中的重复文件及小节。")
    for doc in selected:
        doc.metadata["_selected_tax_scope"] = tax_type
    return selected

def read_menu_standard_answer(docs, tax_type):
    """Only remove heading and ingest labels; never rewrite authored answer text."""
    answer = render_document_sections(docs, tax_type)
    if not answer or re.match(r"^[（(]*(?:参见|详见|see\b)", answer, re.I):
        raise FixedMenuAnswerError("标准答案为空或只有引用；请补充标准答案正文。")
    return answer

def main(config_path="config.json", db_dir="db"):
    configure(config_path=config_path, db_dir=db_dir)
    if not Path(DB_DIR).is_dir():
        raise SystemExit(
            f"Database directory not found: {DB_DIR}. Run ingest.py first."
        )

    embeddings = OllamaEmbeddings(
        model=EMBEDDING_MODEL
    )

    print("RAG QA is ready.")
    print("输入 exit、quit 或 q 可以退出。")
    print()

    while True:
        MENU_SELECTION_HISTORY.clear()
        try:
            topic_name = ask_for_topic()
        except ExitRequested:
            break

        topic_config = TOPIC_CONFIG[topic_name]
        language = topic_config["language"]
        collection_name = COLLECTIONS[language]
        language_name = LANGUAGE_NAMES[language]

        try:
            scenario_key = topic_config.get("default_scenario")
            if scenario_key is None:
                scenario_key = ask_for_scenario(topic_name)

            base_scenario_config = topic_config["scenarios"][scenario_key]
            resolve_before_tax = topic_config.get(
                "resolve_scenario_before_tax",
                False,
            )

            if resolve_before_tax:
                scenario_config = resolve_scenario_config(
                    topic_name=topic_name,
                    scenario_key=scenario_key,
                    selected_tax_types=base_scenario_config.get(
                        "tax_types",
                        topic_config["tax_types"],
                    ),
                )
                tax_scope_config = scenario_config
            else:
                tax_scope_config = base_scenario_config

            available_tax_types = list(
                tax_scope_config.get(
                    "tax_types",
                    topic_config["tax_types"],
                )
            )
            ask_tax_type_enabled = tax_scope_config.get(
                "ask_tax_type",
                topic_config.get("ask_tax_type", True),
            )
            if ask_tax_type_enabled:
                tax_types = [ask_for_tax_type(available_tax_types)]
            else:
                tax_types = available_tax_types

            if not resolve_before_tax:
                scenario_config = resolve_scenario_config(
                    topic_name=topic_name,
                    scenario_key=scenario_key,
                    selected_tax_types=tax_types,
                )
        except ExitRequested:
            break
        except PreviousMenuRequested:
            continue

        print("\nSearching knowledge base...")
        print(f"Detected language: {language_name}")
        print(f"Using collection: {collection_name}")

        print(f"Detected topic: {topic_name}")
        print("Selected scenario: " + scenario_config["label"])
        print("Detected tax type(s): " + ", ".join(tax_types))

        print("Question scope: fixed menu standard answer")

        start_time = time.time()

        vectorstore = get_vector_store(
            language=language,
            embeddings=embeddings,
        )

        try:
            docs = get_menu_standard_answer_chunks(
                vectorstore, topic_name, scenario_config, tax_types[0]
            )
            retrieval_time = time.time()
            if docs:
                print_selected_context(docs=docs, mode="fixed menu standard answer")
                answer = read_menu_standard_answer(docs, tax_types[0])
            else:
                answer = "知识库未收录该场景的相关答案。"
        except FixedMenuAnswerError as exc:
            print("\n文档答案提取失败：" + str(exc) + "\n")
            if not ask_to_continue():
                break
            continue

        print("\nUsing selected knowledge-base text directly; no language-model rewriting.\n")
        print("\nAnswer:")
        print(answer)
        print(f"\nRetrieval Time: {retrieval_time - start_time:.2f}s")
        print("Generation Time: 0.00s")
        print("\n" + "-" * 60 + "\n")
        if not ask_to_continue():
            break

def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="config.json",
        help="Menu configuration JSON (default: config.json)",
    )
    parser.add_argument(
        "--db",
        default="db",
        help="Chroma directory (default: db)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(config_path=args.config, db_dir=args.db)
