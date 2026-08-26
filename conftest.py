# Даёт pytest находить пакет tomostage в src/ без установки пакета
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
