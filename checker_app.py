"""Window version of the checker (entry point of checker.exe): python checker_app.py

With a report link as argument (`scripturechecker:...`, started by Windows) it opens no window: it makes Paratext
show the verse and exits.
"""
import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1].lower().startswith("scripturechecker:"):
        from checker.paratext_link import handle
        handle(sys.argv[1])
    else:
        from checker.gui import main
        main()
