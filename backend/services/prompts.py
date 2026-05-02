"""
Prompt Templates - Text-to-SQL提示词模板
包含：Few-shot模板、Zero-shot模板、Schema格式化
"""

from typing import Dict, List, Optional


class PromptTemplates:
    """Prompt模板管理类"""

    @staticmethod
    def format_schema(tables: List[Dict], comments: Optional[Dict] = None) -> str:
        """
        格式化数据库 Schema 信息，可附加 LLM 生成的字段业务注释。

        Args:
            tables: 表结构列表，每项包含 table_name 和 columns
            comments: 字段注释字典，格式为
                {table_name: {"__table__": "表注释", col_name: "字段注释"}}

        Returns:
            str: 格式化的 Schema 描述
        """
        comments = comments or {}
        schema_text = "数据库表结构：\n"

        for table in tables:
            table_name = table.get("table_name", "")
            columns = table.get("columns", [])
            table_comments = comments.get(table_name, {})

            table_comment = table_comments.get("__table__", "")
            if table_comment:
                schema_text += f"\n表名：{table_name}（{table_comment}）\n"
            else:
                schema_text += f"\n表名：{table_name}\n"

            schema_text += "字段：\n"
            for col in columns:
                col_name = col.get("name", "")
                col_type = col.get("type", "")
                col_comment = table_comments.get(col_name, "")
                if col_comment:
                    schema_text += f"  - {col_name} ({col_type})  # {col_comment}\n"
                else:
                    schema_text += f"  - {col_name} ({col_type})\n"

        return schema_text.strip()

    @staticmethod
    def format_examples(examples: List[Dict]) -> str:
        """
        格式化Few-shot示例

        Args:
            examples: 示例列表
                [
                    {
                        "query": "查询所有订单",
                        "sql": "SELECT * FROM orders;"
                    },
                    ...
                ]

        Returns:
            str: 格式化的示例文本
        """
        examples_text = "参考示例：\n"

        for i, example in enumerate(examples, 1):
            query = example.get("query", "")
            sql = example.get("sql", "")

            examples_text += f"\n示例 {i}：\n"
            examples_text += f"用户查询：{query}\n"
            examples_text += f"SQL语句：\n```sql\n{sql}\n```\n"

        return examples_text.strip()

    @staticmethod
    def build_few_shot_prompt(
            user_query: str,
            schema: str,
            examples: List[Dict],
            constraints: Optional[str] = None
    ) -> str:
        """
        构建Few-shot Prompt

        Args:
            user_query: 用户的自然语言查询
            schema: 格式化的Schema信息
            examples: Few-shot示例列表
            constraints: 额外的约束条件（可选）

        Returns:
            str: 完整的Few-shot prompt
        """
        # 基础约束
        base_constraints = """
生成要求：
1. 只输出SQL语句，不要有任何解释或说明
2. SQL语句必须用```sql和```包裹
3. 确保SQL语法正确，符合SQLite标准
4. 字段名、表名必须与Schema完全一致
5. 对于中文查询，理解语义后生成对应的SQL
6. 使用标准SQL语法（SELECT, WHERE, GROUP BY, ORDER BY等）
7. 日期时间使用YYYY-MM-DD HH:MM:SS格式
"""

        # 合并约束
        final_constraints = base_constraints
        if constraints:
            final_constraints += f"\n{constraints}"

        # 构建完整prompt
        prompt = f"""你是一个专业的SQL生成助手。请根据以下信息生成准确的SQL查询语句。

{schema}

{PromptTemplates.format_examples(examples)}

{final_constraints}

当前查询：
用户查询：{user_query}
SQL语句：
"""

        return prompt.strip()

    @staticmethod
    def build_zero_shot_prompt(
            user_query: str,
            schema: str,
            constraints: Optional[str] = None
    ) -> str:
        """
        构建Zero-shot Prompt（无示例）

        Args:
            user_query: 用户的自然语言查询
            schema: 格式化的Schema信息
            constraints: 额外的约束条件（可选）

        Returns:
            str: 完整的Zero-shot prompt
        """
        # 基础约束
        base_constraints = """
生成要求：
1. 只输出SQL语句，不要有任何解释或说明
2. SQL语句必须用```sql和```包裹
3. 确保SQL语法正确，符合SQLite标准
4. 字段名、表名必须与Schema完全一致
5. 对于复杂查询，可以使用JOIN、子查询、聚合函数等
6. 优先使用简洁高效的SQL写法
7. 日期时间使用YYYY-MM-DD HH:MM:SS格式
8. 理解查询意图，生成最符合语义的SQL
"""

        # 合并约束
        final_constraints = base_constraints
        if constraints:
            final_constraints += f"\n{constraints}"

        # 构建完整prompt
        prompt = f"""你是一个专业的SQL生成助手。请根据以下数据库结构和用户查询，生成准确的SQL语句。

{schema}

{final_constraints}

用户查询：{user_query}

请生成对应的SQL语句：
"""

        return prompt.strip()

    @staticmethod
    def build_rule_based_prompt(
            user_query: str,
            schema: str,
            rule_type: str = "simple_select"
    ) -> str:
        """
        构建规则层Prompt（用于简单查询）

        Args:
            user_query: 用户查询
            schema: Schema信息
            rule_type: 规则类型（simple_select, simple_filter等）

        Returns:
            str: 规则层prompt
        """
        if rule_type == "simple_select":
            template = f"""请为以下查询生成SQL语句：

{schema}

用户查询：{user_query}

这是一个简单的SELECT查询，请直接输出SQL，格式如下：
```sql
SELECT * FROM table_name;
```
"""

        elif rule_type == "simple_filter":
            template = f"""请为以下查询生成SQL语句：

{schema}

用户查询：{user_query}

这是一个简单的筛选查询，请直接输出SQL，格式如下：
```sql
SELECT * FROM table_name WHERE condition;
```
"""

        else:
            # 默认使用simple_select
            template = PromptTemplates.build_rule_based_prompt(
                user_query, schema, "simple_select"
            )

        return template.strip()


# 预定义的常用约束
class CommonConstraints:
    """常用的SQL生成约束"""

    # 安全约束
    SECURITY = """
安全要求：
- 禁止使用DROP、DELETE、UPDATE、INSERT等修改操作
- 禁止使用TRUNCATE、ALTER等DDL操作
- 只允许使用SELECT查询语句
"""

    # 性能约束
    PERFORMANCE = """
性能要求：
- 避免使用SELECT *，明确指定需要的字段
- 合理使用LIMIT限制返回行数
- 对于大表查询，优先使用索引字段作为筛选条件
"""

    # 数据类型约束
    DATA_TYPES = """
数据类型说明：
- 日期字段：使用 DATE() 或 DATETIME() 函数
- 字符串匹配：使用 LIKE 操作符，% 表示通配符
- 数值比较：直接使用 <, >, =, >=, <= 等操作符
- 空值判断：使用 IS NULL 或 IS NOT NULL
"""

    # 聚合查询约束
    AGGREGATION = """
聚合查询说明：
- 使用 COUNT(), SUM(), AVG(), MAX(), MIN() 等聚合函数
- 使用 GROUP BY 进行分组
- 使用 HAVING 进行分组后筛选
- 使用 ORDER BY 进行排序
"""


# 测试函数
def test_prompt_templates():
    """测试Prompt模板生成"""
    print("=" * 60)
    print("测试Prompt模板")
    print("=" * 60)

    # 模拟Schema
    schema = PromptTemplates.format_schema([
        {
            "table_name": "orders",
            "columns": [
                {"name": "InvoiceNo", "type": "TEXT"},
                {"name": "StockCode", "type": "TEXT"},
                {"name": "Description", "type": "TEXT"},
                {"name": "Quantity", "type": "INTEGER"},
                {"name": "InvoiceDate", "type": "TEXT"},
                {"name": "UnitPrice", "type": "REAL"},
                {"name": "CustomerID", "type": "TEXT"},
                {"name": "Country", "type": "TEXT"}
            ]
        }
    ])

    # 模拟Few-shot示例
    examples = [
        {
            "query": "查询所有订单",
            "sql": "SELECT * FROM orders;"
        },
        {
            "query": "查询英国的订单",
            "sql": "SELECT * FROM orders WHERE Country = 'United Kingdom';"
        }
    ]

    user_query = "查询数量大于10的订单"

    # 测试1: Few-shot Prompt
    print("\n【测试1：Few-shot Prompt】")
    print("-" * 60)
    few_shot = PromptTemplates.build_few_shot_prompt(
        user_query=user_query,
        schema=schema,
        examples=examples,
        constraints=CommonConstraints.SECURITY
    )
    print(few_shot)

    # 测试2: Zero-shot Prompt
    print("\n\n【测试2：Zero-shot Prompt】")
    print("-" * 60)
    zero_shot = PromptTemplates.build_zero_shot_prompt(
        user_query=user_query,
        schema=schema,
        constraints=CommonConstraints.SECURITY
    )
    print(zero_shot)

    # 测试3: Rule-based Prompt
    print("\n\n【测试3：Rule-based Prompt】")
    print("-" * 60)
    rule_based = PromptTemplates.build_rule_based_prompt(
        user_query="查询所有订单",
        schema=schema,
        rule_type="simple_select"
    )
    print(rule_based)

    print("\n" + "=" * 60)
    print("测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    test_prompt_templates()