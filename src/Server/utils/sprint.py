"""Simple Module that prints onto the console"""


class Logger:
    """Class that prints different types of messages to the console"""

    GREEN = "\033[32m"
    RED = "\033[31m"
    RESET = "\033[0m"
    YELLOW = "\033[33m"

    INFO_PREFIX = f"{GREEN}[INFO]:  {RESET}"
    ERROR_PREFIX = f"{RED}[ERROR]:  {RESET}"
    TEST_PREFIX = f"{GREEN}[TEST]:  {RESET}"
    DEBUG_PREFIX = f"{YELLOW}[DEBUG]: {RESET}"

    _instance = None

    def __init__(self, debug=False):
        """Initialize the Logger instance (singleton)."""
        if Logger._instance is not None:
            raise RuntimeError(
                "Use Logger.get_instance() to get the singleton instance"
            )
        self.debug = debug
        Logger._instance = self  # Set the singleton instance

    @staticmethod
    def get_instance(debug=False):
        """Returns the singleton instance of Logger. Allows setting debug mode if not already initialized."""
        if Logger._instance is None:
            Logger._instance = Logger(debug)
        else:
            Logger._instance.debug = debug  # Update debug mode if re-requested
        return Logger._instance

    @staticmethod
    def tprint(*messages):
        """Prints a test message. Accepts multiple messages."""
        print(Logger.TEST_PREFIX, " ".join(map(str, messages)))

    @staticmethod
    def iprint(*messages):
        """Prints an info message. Accepts multiple messages."""
        print(Logger.INFO_PREFIX, " ".join(map(str, messages)))

    @staticmethod
    def eprint(*messages):
        """Prints an error message. Accepts multiple messages."""
        print(Logger.ERROR_PREFIX, " ".join(map(str, messages)))

    def dprint(self, *messages):
        """Prints a debug message only if debug mode is enabled. Accepts multiple messages."""
        if self.debug:
            print(Logger.DEBUG_PREFIX, " ".join(map(str, messages)))
