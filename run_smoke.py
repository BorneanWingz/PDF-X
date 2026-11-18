import faulthandler
import runpy

faulthandler.dump_traceback_later(60, exit=True)
runpy.run_path("scripts/gui_smoke.py", run_name="__main__")
