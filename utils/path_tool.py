"""
为整个工程提供统一的绝对路径
"""
import os

def get_project_root_path():
    """
    获取项目根目录
    :return:
    """
    current_file = os.path.abspath(__file__)        # 当前文件绝对路径
    return os.path.dirname(os.path.dirname(current_file))       # 获取项目根目录

def get_abs_path(file_path: str)-> str:
    """
    获得文件相对路径,返回绝对路径字符串
    :param file_path:
    :return:
    """
    project_path = get_project_root_path()
    return os.path.join(project_path, file_path)

if __name__ == '__main__':
    print(get_abs_path("path_tool.py"))