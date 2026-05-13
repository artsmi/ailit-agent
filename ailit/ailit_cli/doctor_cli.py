"""`ailit doctor`: диагностика установки и политики данных (DP-5.2)."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from ailit_cli.user_paths import GlobalDirResolver


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Снимок диагностики."""

    ailit_home: Path
    global_config_dir: Path
    global_state_dir: Path
    global_logs_dir: Path
    executable: Path
    python: Path


class Doctor:
    """Сбор диагностики в одном месте."""

    def collect(self) -> DoctorReport:
        """Собрать paths/окружение."""
        r = GlobalDirResolver(os.environ)
        st = r.global_state_dir()
        exe = Path(sys.argv[0]).resolve()
        py = Path(sys.executable).resolve()
        return DoctorReport(
            ailit_home=r.ailit_home(),
            global_config_dir=r.global_config_dir(),
            global_state_dir=st,
            global_logs_dir=st / "logs",
            executable=exe,
            python=py,
        )


def cmd_doctor_paths() -> int:
    """Печать путей и исполняемых файлов."""
    rep = Doctor().collect()
    sys.stdout.write(f"ailit_home={rep.ailit_home}\n")
    sys.stdout.write(f"global_config_dir={rep.global_config_dir}\n")
    sys.stdout.write(f"global_state_dir={rep.global_state_dir}\n")
    sys.stdout.write(f"global_logs_dir={rep.global_logs_dir}\n")
    sys.stdout.write(f"executable={rep.executable}\n")
    sys.stdout.write(f"python={rep.python}\n")
    return 0


def cmd_doctor_data_policy() -> int:
    """Печать политики данных пользователя."""
    rep = Doctor().collect()
    sys.stdout.write("Сохраняется при обновлении/удалении пакета:\n")
    sys.stdout.write(f"- {rep.ailit_home}  (глобальный дом)\n")
    sys.stdout.write(f"- {rep.global_config_dir}  (конфиг)\n")
    sys.stdout.write(f"- {rep.global_state_dir}  (сессии/логи)\n")
    sys.stdout.write("\nУдаляется вместе с установкой (venv/пакет):\n")
    sys.stdout.write(
        "- зависит от способа установки (pip/venv); ~/.ailit не трогаем\n"
    )
    return 0
