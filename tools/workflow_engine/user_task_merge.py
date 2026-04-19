"""Подмешивание CLI-задачи к первому user-сообщению задачи workflow (этап K.1)."""


def merge_cli_task_into_first_user_message(*, workflow_user_text: str, cli_body: str) -> str:
    """Склеить тело CLI-задачи и шаблон ``user_text`` из YAML."""
    cli = cli_body.rstrip()
    base = workflow_user_text.strip()
    if not cli:
        return workflow_user_text
    if not base:
        return cli
    return f"{cli}\n\n---\n\n{base}"
