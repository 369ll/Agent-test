class IntegrationError(RuntimeError):
    """集成层基础错误。"""


class TransientIntegrationError(IntegrationError):
    """可重试的集成层错误。"""
