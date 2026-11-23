"""Recognize model-format failures recorded by the primary and early-version runners."""
import ast


def format_failure(description):
    """Recognize only the exact JSON error, including nested TaskGroup exceptions."""
    if description=='Model returned invalid JSON twice.':
        return True
    def matches(node):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.keywords:
            return False
        if node.func.id=='ValueError' and len(node.args)==1:
            return isinstance(node.args[0],ast.Constant) and node.args[0].value=='Model returned invalid JSON twice.'
        if node.func.id in ('ExceptionGroup','BaseExceptionGroup') and len(node.args)==2:
            errors=node.args[1]
            return isinstance(errors,ast.List) and bool(errors.elts) and all(matches(e) for e in errors.elts)
        return False
    try:
        return matches(ast.parse(description,mode='eval').body)
    except (ValueError, SyntaxError, TypeError):
        return False
