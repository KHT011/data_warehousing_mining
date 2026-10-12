"""Execute the notebook, independent reconciliation and compact report."""
from mining.preliminary import main
from mining.preliminary_validate import validate_result
from mining.preliminary_report import build_report


if __name__ == '__main__':
    main()
    validate_result()
    build_report()
