"""120 个问数场景目录：覆盖数仓星型模型的过滤、聚合、分组和空结果。"""

from typing import TypedDict


class QueryScenario(TypedDict):
    id: str
    category: str
    question: str
    expected_tables: list[str]
    expected_metrics: list[str]
    gold_sql: str
    expect_empty: bool


def _scenario(
    item_id: str,
    category: str,
    question: str,
    tables: list[str],
    metrics: list[str],
    gold_sql: str,
    expect_empty: bool = False,
) -> QueryScenario:
    return {
        "id": item_id,
        "category": category,
        "question": question,
        "expected_tables": tables,
        "expected_metrics": metrics,
        "gold_sql": " ".join(gold_sql.split()),
        "expect_empty": expect_empty,
    }


def build_query_scenarios() -> list[QueryScenario]:
    """构造恰好 120 条可在教学数仓上执行的问数场景。"""
    fact = ["fact_order"]
    region = ["fact_order", "dim_region"]
    customer = ["fact_order", "dim_customer"]
    product = ["fact_order", "dim_product"]
    date = ["fact_order", "dim_date"]
    scenarios: list[QueryScenario] = []

    scenarios.extend(
        [
            _scenario(
                "G001",
                "global_agg",
                "统计全部订单的销售总额",
                fact,
                ["GMV"],
                "SELECT ROUND(SUM(order_amount), 2) AS gmv FROM fact_order",
            ),
            _scenario(
                "G002",
                "global_agg",
                "查询全站成交总额 GMV",
                fact,
                ["GMV"],
                "SELECT ROUND(SUM(order_amount), 2) AS gmv FROM fact_order",
            ),
            _scenario(
                "G003",
                "global_agg",
                "计算所有订单的平均订单金额",
                fact,
                ["AOV"],
                "SELECT ROUND(AVG(order_amount), 2) AS aov FROM fact_order",
            ),
            _scenario(
                "G004",
                "global_agg",
                "统计 AOV 平均单价",
                fact,
                ["AOV"],
                "SELECT ROUND(AVG(order_amount), 2) AS aov FROM fact_order",
            ),
            _scenario(
                "G005",
                "global_agg",
                "统计全部订单销量",
                fact,
                [],
                "SELECT SUM(order_quantity) AS qty FROM fact_order",
            ),
            _scenario(
                "G006",
                "global_agg",
                "一共有多少笔订单",
                fact,
                [],
                "SELECT COUNT(*) AS order_cnt FROM fact_order",
            ),
            _scenario(
                "G007",
                "global_agg",
                "统计订单总收入",
                fact,
                ["GMV"],
                "SELECT ROUND(SUM(order_amount), 2) AS gmv FROM fact_order",
            ),
            _scenario(
                "G008",
                "global_agg",
                "查询最大单笔订单金额",
                fact,
                [],
                "SELECT ROUND(MAX(order_amount), 2) AS max_amount FROM fact_order",
            ),
        ]
    )

    for index, name in enumerate(["华北", "华东", "华南", "西南", "华中"], start=1):
        scenarios.append(
            _scenario(
                f"R{index:03d}",
                "region",
                f"统计{name}地区的销售总额",
                region,
                ["GMV"],
                f"""
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                WHERE r.region_name = '{name}'
                """,
            )
        )
    for index, name in enumerate(["华北", "华东", "华南"], start=6):
        scenarios.append(
            _scenario(
                f"R{index:03d}",
                "region",
                f"{name}大区的订单数量是多少",
                region,
                [],
                f"""
                SELECT COUNT(*) AS order_cnt
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                WHERE r.region_name = '{name}'
                """,
            )
        )
    for index, province in enumerate(
        ["北京市", "上海市", "广东省", "浙江省", "四川省"], start=9
    ):
        scenarios.append(
            _scenario(
                f"R{index:03d}",
                "region",
                f"统计{province}的销售额",
                region,
                ["GMV"],
                f"""
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                WHERE r.province = '{province}'
                """,
            )
        )
    scenarios.extend(
        [
            _scenario(
                "R014",
                "region",
                "按大区统计销售总额",
                region,
                ["GMV"],
                """
                SELECT r.region_name, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                GROUP BY r.region_name
                ORDER BY gmv DESC
                """,
            ),
            _scenario(
                "R015",
                "region",
                "中国地区的成交总额是多少",
                region,
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                WHERE r.country = '中国'
                """,
            ),
            _scenario(
                "R016",
                "region",
                "湖北省的订单销量合计",
                region,
                [],
                """
                SELECT SUM(o.order_quantity) AS qty
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                WHERE r.province = '湖北省'
                """,
            ),
        ]
    )

    for index, level in enumerate(["黄金", "白银", "青铜", "铂金"], start=1):
        scenarios.append(
            _scenario(
                f"C{index:03d}",
                "customer",
                f"统计{level}会员的销售总额",
                customer,
                ["GMV"],
                f"""
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_customer c ON o.customer_id = c.customer_id
                WHERE c.member_level = '{level}'
                """,
            )
        )
    for index, gender in enumerate(["男", "女"], start=5):
        scenarios.append(
            _scenario(
                f"C{index:03d}",
                "customer",
                f"{gender}性客户的成交总额",
                customer,
                ["GMV"],
                f"""
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_customer c ON o.customer_id = c.customer_id
                WHERE c.gender = '{gender}'
                """,
            )
        )
    for index, name in enumerate(["李伟", "王芳", "陈静", "吴斌"], start=7):
        scenarios.append(
            _scenario(
                f"C{index:03d}",
                "customer",
                f"客户{name}的订单总额",
                customer,
                ["GMV"],
                f"""
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_customer c ON o.customer_id = c.customer_id
                WHERE c.customer_name = '{name}'
                """,
            )
        )
    scenarios.extend(
        [
            _scenario(
                "C011",
                "customer",
                "按会员等级统计销售额",
                customer,
                ["GMV"],
                """
                SELECT c.member_level, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_customer c ON o.customer_id = c.customer_id
                GROUP BY c.member_level
                ORDER BY gmv DESC
                """,
            ),
            _scenario(
                "C012",
                "customer",
                "女性铂金会员的平均订单金额",
                customer,
                ["AOV"],
                """
                SELECT ROUND(AVG(o.order_amount), 2) AS aov
                FROM fact_order o
                JOIN dim_customer c ON o.customer_id = c.customer_id
                WHERE c.gender = '女' AND c.member_level = '铂金'
                """,
            ),
            _scenario(
                "C013",
                "customer",
                "男性黄金会员买了多少件商品",
                customer,
                [],
                """
                SELECT SUM(o.order_quantity) AS qty
                FROM fact_order o
                JOIN dim_customer c ON o.customer_id = c.customer_id
                WHERE c.gender = '男' AND c.member_level = '黄金'
                """,
            ),
            _scenario(
                "C014",
                "customer",
                "有多少个不同客户下过单",
                fact,
                [],
                "SELECT COUNT(DISTINCT customer_id) AS customer_cnt FROM fact_order",
            ),
            _scenario(
                "C015",
                "customer",
                "青铜会员的订单笔数",
                customer,
                [],
                """
                SELECT COUNT(*) AS order_cnt
                FROM fact_order o
                JOIN dim_customer c ON o.customer_id = c.customer_id
                WHERE c.member_level = '青铜'
                """,
            ),
            _scenario(
                "C016",
                "customer",
                "按性别统计成交总额",
                customer,
                ["GMV"],
                """
                SELECT c.gender, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_customer c ON o.customer_id = c.customer_id
                GROUP BY c.gender
                """,
            ),
        ]
    )

    for index, category in enumerate(
        ["手机数码", "家用电器", "鞋靴", "服饰", "食品饮料", "休闲零食"], start=1
    ):
        scenarios.append(
            _scenario(
                f"P{index:03d}",
                "product",
                f"统计{category}品类的销售总额",
                product,
                ["GMV"],
                f"""
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_product p ON o.product_id = p.product_id
                WHERE p.category = '{category}'
                """,
            )
        )
    for index, brand in enumerate(
        ["苹果", "华为", "耐克", "美的", "雀巢", "乐事"], start=7
    ):
        scenarios.append(
            _scenario(
                f"P{index:03d}",
                "product",
                f"{brand}品牌的销售额是多少",
                product,
                ["GMV"],
                f"""
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_product p ON o.product_id = p.product_id
                WHERE p.brand = '{brand}'
                """,
            )
        )
    scenarios.extend(
        [
            _scenario(
                "P013",
                "product",
                "iPhone 15 Pro 卖了多少钱",
                product,
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_product p ON o.product_id = p.product_id
                WHERE p.product_name = 'iPhone 15 Pro'
                """,
            ),
            _scenario(
                "P014",
                "product",
                "按品类统计销量",
                product,
                [],
                """
                SELECT p.category, SUM(o.order_quantity) AS qty
                FROM fact_order o
                JOIN dim_product p ON o.product_id = p.product_id
                GROUP BY p.category
                ORDER BY qty DESC
                """,
            ),
            _scenario(
                "P015",
                "product",
                "三星商品的订单数量",
                product,
                [],
                """
                SELECT COUNT(*) AS order_cnt
                FROM fact_order o
                JOIN dim_product p ON o.product_id = p.product_id
                WHERE p.brand = '三星'
                """,
            ),
            _scenario(
                "P016",
                "product",
                "戴森吸尘器的成交总额",
                product,
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_product p ON o.product_id = p.product_id
                WHERE p.product_name = '戴森 V15 吸尘器'
                """,
            ),
        ]
    )

    scenarios.extend(
        [
            _scenario(
                "T001",
                "time",
                "统计2025年的销售总额",
                date,
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_date d ON o.date_id = d.date_id
                WHERE d.year = 2025
                """,
            ),
            _scenario(
                "T002",
                "time",
                "2025年第一季度的成交总额",
                date,
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_date d ON o.date_id = d.date_id
                WHERE d.year = 2025 AND d.quarter = 'Q1'
                """,
            ),
            _scenario(
                "T003",
                "time",
                "2025年1月的销售额",
                date,
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_date d ON o.date_id = d.date_id
                WHERE d.year = 2025 AND d.month = 1
                """,
            ),
            _scenario(
                "T004",
                "time",
                "2025年2月的订单总额",
                date,
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_date d ON o.date_id = d.date_id
                WHERE d.year = 2025 AND d.month = 2
                """,
            ),
            _scenario(
                "T005",
                "time",
                "2025年3月卖了多少钱",
                date,
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_date d ON o.date_id = d.date_id
                WHERE d.year = 2025 AND d.month = 3
                """,
            ),
            _scenario(
                "T006",
                "time",
                "按月份统计2025年销售额",
                date,
                ["GMV"],
                """
                SELECT d.month, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_date d ON o.date_id = d.date_id
                WHERE d.year = 2025
                GROUP BY d.month
                ORDER BY d.month
                """,
            ),
            _scenario(
                "T007",
                "time",
                "2025年1月1日的销售额",
                date,
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                WHERE o.date_id = 20250101
                """,
            ),
            _scenario(
                "T008",
                "time",
                "2025年3月31日成交了多少",
                date,
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                WHERE o.date_id = 20250331
                """,
            ),
            _scenario(
                "T009",
                "time",
                "一月份的订单笔数",
                date,
                [],
                """
                SELECT COUNT(*) AS order_cnt
                FROM fact_order o
                JOIN dim_date d ON o.date_id = d.date_id
                WHERE d.month = 1
                """,
            ),
            _scenario(
                "T010",
                "time",
                "第一季度的平均订单金额",
                date,
                ["AOV"],
                """
                SELECT ROUND(AVG(o.order_amount), 2) AS aov
                FROM fact_order o
                JOIN dim_date d ON o.date_id = d.date_id
                WHERE d.quarter = 'Q1'
                """,
            ),
            _scenario(
                "T011",
                "time",
                "2025年2月的销量合计",
                date,
                [],
                """
                SELECT SUM(o.order_quantity) AS qty
                FROM fact_order o
                JOIN dim_date d ON o.date_id = d.date_id
                WHERE d.year = 2025 AND d.month = 2
                """,
            ),
            _scenario(
                "T012",
                "time",
                "按季度统计销售额",
                date,
                ["GMV"],
                """
                SELECT d.quarter, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_date d ON o.date_id = d.date_id
                GROUP BY d.quarter
                """,
            ),
            _scenario(
                "T013",
                "time",
                "3月18日的订单金额",
                date,
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                WHERE o.date_id = 20250318
                """,
            ),
            _scenario(
                "T014",
                "time",
                "2025年春节后2月的成交总额",
                date,
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_date d ON o.date_id = d.date_id
                WHERE d.year = 2025 AND d.month = 2
                """,
            ),
            _scenario(
                "T015",
                "time",
                "统计1月到3月的总销售额",
                date,
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_date d ON o.date_id = d.date_id
                WHERE d.month IN (1, 2, 3)
                """,
            ),
            _scenario(
                "T016",
                "time",
                "2025年每天的订单笔数最多是哪天",
                date,
                [],
                """
                SELECT o.date_id, COUNT(*) AS order_cnt
                FROM fact_order o
                GROUP BY o.date_id
                ORDER BY order_cnt DESC, o.date_id
                LIMIT 1
                """,
            ),
        ]
    )

    scenarios.extend(
        [
            _scenario(
                "B001",
                "group_by",
                "按大区汇总 GMV",
                region,
                ["GMV"],
                """
                SELECT r.region_name, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                GROUP BY r.region_name
                """,
            ),
            _scenario(
                "B002",
                "group_by",
                "按省份汇总销售额",
                region,
                ["GMV"],
                """
                SELECT r.province, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                GROUP BY r.province
                """,
            ),
            _scenario(
                "B003",
                "group_by",
                "按品牌统计成交总额",
                product,
                ["GMV"],
                """
                SELECT p.brand, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_product p ON o.product_id = p.product_id
                GROUP BY p.brand
                """,
            ),
            _scenario(
                "B004",
                "group_by",
                "按品类统计平均订单金额",
                product,
                ["AOV"],
                """
                SELECT p.category, ROUND(AVG(o.order_amount), 2) AS aov
                FROM fact_order o
                JOIN dim_product p ON o.product_id = p.product_id
                GROUP BY p.category
                """,
            ),
            _scenario(
                "B005",
                "group_by",
                "按会员等级汇总销量",
                customer,
                [],
                """
                SELECT c.member_level, SUM(o.order_quantity) AS qty
                FROM fact_order o
                JOIN dim_customer c ON o.customer_id = c.customer_id
                GROUP BY c.member_level
                """,
            ),
            _scenario(
                "B006",
                "group_by",
                "按性别和会员等级统计销售额",
                customer,
                ["GMV"],
                """
                SELECT c.gender, c.member_level, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_customer c ON o.customer_id = c.customer_id
                GROUP BY c.gender, c.member_level
                """,
            ),
            _scenario(
                "B007",
                "group_by",
                "按商品名称汇总订单金额",
                product,
                ["GMV"],
                """
                SELECT p.product_name, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_product p ON o.product_id = p.product_id
                GROUP BY p.product_name
                """,
            ),
            _scenario(
                "B008",
                "group_by",
                "各大区的订单笔数",
                region,
                [],
                """
                SELECT r.region_name, COUNT(*) AS order_cnt
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                GROUP BY r.region_name
                """,
            ),
            _scenario(
                "B009",
                "group_by",
                "按月份和品类统计销售额",
                ["fact_order", "dim_date", "dim_product"],
                ["GMV"],
                """
                SELECT d.month, p.category, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_date d ON o.date_id = d.date_id
                JOIN dim_product p ON o.product_id = p.product_id
                GROUP BY d.month, p.category
                """,
            ),
            _scenario(
                "B010",
                "group_by",
                "每个客户的累计消费金额",
                customer,
                ["GMV"],
                """
                SELECT c.customer_name, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_customer c ON o.customer_id = c.customer_id
                GROUP BY c.customer_name
                """,
            ),
            _scenario(
                "B011",
                "group_by",
                "按国家和大区统计收入",
                region,
                ["GMV"],
                """
                SELECT r.country, r.region_name, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                GROUP BY r.country, r.region_name
                """,
            ),
            _scenario(
                "B012",
                "group_by",
                "各品牌的平均订单金额",
                product,
                ["AOV"],
                """
                SELECT p.brand, ROUND(AVG(o.order_amount), 2) AS aov
                FROM fact_order o
                JOIN dim_product p ON o.product_id = p.product_id
                GROUP BY p.brand
                """,
            ),
            _scenario(
                "B013",
                "group_by",
                "按天下单金额汇总",
                fact,
                ["GMV"],
                """
                SELECT date_id, ROUND(SUM(order_amount), 2) AS gmv
                FROM fact_order
                GROUP BY date_id
                ORDER BY date_id
                """,
            ),
            _scenario(
                "B014",
                "group_by",
                "各品类订单件数",
                product,
                [],
                """
                SELECT p.category, SUM(o.order_quantity) AS qty
                FROM fact_order o
                JOIN dim_product p ON o.product_id = p.product_id
                GROUP BY p.category
                """,
            ),
            _scenario(
                "B015",
                "group_by",
                "按省份和品类交叉统计销售额",
                ["fact_order", "dim_region", "dim_product"],
                ["GMV"],
                """
                SELECT r.province, p.category, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                JOIN dim_product p ON o.product_id = p.product_id
                GROUP BY r.province, p.category
                """,
            ),
            _scenario(
                "B016",
                "group_by",
                "会员等级在各月的销售额",
                ["fact_order", "dim_customer", "dim_date"],
                ["GMV"],
                """
                SELECT d.month, c.member_level, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_date d ON o.date_id = d.date_id
                JOIN dim_customer c ON o.customer_id = c.customer_id
                GROUP BY d.month, c.member_level
                """,
            ),
        ]
    )

    scenarios.extend(
        [
            _scenario(
                "X001",
                "combo",
                "统计华北地区手机数码的销售总额",
                ["fact_order", "dim_region", "dim_product"],
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                JOIN dim_product p ON o.product_id = p.product_id
                WHERE r.region_name = '华北' AND p.category = '手机数码'
                """,
            ),
            _scenario(
                "X002",
                "combo",
                "华东大区苹果品牌卖了多少钱",
                ["fact_order", "dim_region", "dim_product"],
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                JOIN dim_product p ON o.product_id = p.product_id
                WHERE r.region_name = '华东' AND p.brand = '苹果'
                """,
            ),
            _scenario(
                "X003",
                "combo",
                "女性客户在华南的成交总额",
                ["fact_order", "dim_region", "dim_customer"],
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                JOIN dim_customer c ON o.customer_id = c.customer_id
                WHERE r.region_name = '华南' AND c.gender = '女'
                """,
            ),
            _scenario(
                "X004",
                "combo",
                "黄金会员2025年1月的销售额",
                ["fact_order", "dim_customer", "dim_date"],
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_customer c ON o.customer_id = c.customer_id
                JOIN dim_date d ON o.date_id = d.date_id
                WHERE c.member_level = '黄金' AND d.year = 2025 AND d.month = 1
                """,
            ),
            _scenario(
                "X005",
                "combo",
                "北京市家用电器品类销售额",
                ["fact_order", "dim_region", "dim_product"],
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                JOIN dim_product p ON o.product_id = p.product_id
                WHERE r.province = '北京市' AND p.category = '家用电器'
                """,
            ),
            _scenario(
                "X006",
                "combo",
                "2025年3月休闲零食的销量",
                ["fact_order", "dim_date", "dim_product"],
                [],
                """
                SELECT SUM(o.order_quantity) AS qty
                FROM fact_order o
                JOIN dim_date d ON o.date_id = d.date_id
                JOIN dim_product p ON o.product_id = p.product_id
                WHERE d.year = 2025 AND d.month = 3 AND p.category = '休闲零食'
                """,
            ),
            _scenario(
                "X007",
                "combo",
                "铂金会员购买华为商品的总额",
                ["fact_order", "dim_customer", "dim_product"],
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_customer c ON o.customer_id = c.customer_id
                JOIN dim_product p ON o.product_id = p.product_id
                WHERE c.member_level = '铂金' AND p.brand = '华为'
                """,
            ),
            _scenario(
                "X008",
                "combo",
                "西南地区第一季度销售额",
                ["fact_order", "dim_region", "dim_date"],
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                JOIN dim_date d ON o.date_id = d.date_id
                WHERE r.region_name = '西南' AND d.quarter = 'Q1'
                """,
            ),
            _scenario(
                "X009",
                "combo",
                "男性客户买鞋靴花了多少钱",
                ["fact_order", "dim_customer", "dim_product"],
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_customer c ON o.customer_id = c.customer_id
                JOIN dim_product p ON o.product_id = p.product_id
                WHERE c.gender = '男' AND p.category = '鞋靴'
                """,
            ),
            _scenario(
                "X010",
                "combo",
                "上海市2025年2月的订单笔数",
                ["fact_order", "dim_region", "dim_date"],
                [],
                """
                SELECT COUNT(*) AS order_cnt
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                JOIN dim_date d ON o.date_id = d.date_id
                WHERE r.province = '上海市' AND d.year = 2025 AND d.month = 2
                """,
            ),
            _scenario(
                "X011",
                "combo",
                "华北黄金会员的平均订单金额",
                ["fact_order", "dim_region", "dim_customer"],
                ["AOV"],
                """
                SELECT ROUND(AVG(o.order_amount), 2) AS aov
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                JOIN dim_customer c ON o.customer_id = c.customer_id
                WHERE r.region_name = '华北' AND c.member_level = '黄金'
                """,
            ),
            _scenario(
                "X012",
                "combo",
                "食品饮料在广东省的销售额",
                ["fact_order", "dim_region", "dim_product"],
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                JOIN dim_product p ON o.product_id = p.product_id
                WHERE r.province = '广东省' AND p.category = '食品饮料'
                """,
            ),
            _scenario(
                "X013",
                "combo",
                "2025年Q1服饰品类成交总额",
                ["fact_order", "dim_date", "dim_product"],
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_date d ON o.date_id = d.date_id
                JOIN dim_product p ON o.product_id = p.product_id
                WHERE d.year = 2025 AND d.quarter = 'Q1' AND p.category = '服饰'
                """,
            ),
            _scenario(
                "X014",
                "combo",
                "华中地区女性客户订单数",
                ["fact_order", "dim_region", "dim_customer"],
                [],
                """
                SELECT COUNT(*) AS order_cnt
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                JOIN dim_customer c ON o.customer_id = c.customer_id
                WHERE r.region_name = '华中' AND c.gender = '女'
                """,
            ),
            _scenario(
                "X015",
                "combo",
                "耐克在华东的销量",
                ["fact_order", "dim_region", "dim_product"],
                [],
                """
                SELECT SUM(o.order_quantity) AS qty
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                JOIN dim_product p ON o.product_id = p.product_id
                WHERE r.region_name = '华东' AND p.brand = '耐克'
                """,
            ),
            _scenario(
                "X016",
                "combo",
                "李伟在华南买了多少金额",
                ["fact_order", "dim_region", "dim_customer"],
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                JOIN dim_customer c ON o.customer_id = c.customer_id
                WHERE r.region_name = '华南' AND c.customer_name = '李伟'
                """,
            ),
        ]
    )

    scenarios.extend(
        [
            _scenario(
                "K001",
                "ranking",
                "销售额最高的大区是哪个",
                region,
                ["GMV"],
                """
                SELECT r.region_name, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                GROUP BY r.region_name
                ORDER BY gmv DESC
                LIMIT 1
                """,
            ),
            _scenario(
                "K002",
                "ranking",
                "GMV 前三的品类",
                product,
                ["GMV"],
                """
                SELECT p.category, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_product p ON o.product_id = p.product_id
                GROUP BY p.category
                ORDER BY gmv DESC
                LIMIT 3
                """,
            ),
            _scenario(
                "K003",
                "ranking",
                "销量最高的商品是什么",
                product,
                [],
                """
                SELECT p.product_name, SUM(o.order_quantity) AS qty
                FROM fact_order o
                JOIN dim_product p ON o.product_id = p.product_id
                GROUP BY p.product_name
                ORDER BY qty DESC
                LIMIT 1
                """,
            ),
            _scenario(
                "K004",
                "ranking",
                "消费金额最高的客户",
                customer,
                ["GMV"],
                """
                SELECT c.customer_name, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_customer c ON o.customer_id = c.customer_id
                GROUP BY c.customer_name
                ORDER BY gmv DESC
                LIMIT 1
                """,
            ),
            _scenario(
                "K005",
                "ranking",
                "销售额前五的品牌",
                product,
                ["GMV"],
                """
                SELECT p.brand, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_product p ON o.product_id = p.product_id
                GROUP BY p.brand
                ORDER BY gmv DESC
                LIMIT 5
                """,
            ),
            _scenario(
                "K006",
                "ranking",
                "订单笔数最多的省份",
                region,
                [],
                """
                SELECT r.province, COUNT(*) AS order_cnt
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                GROUP BY r.province
                ORDER BY order_cnt DESC
                LIMIT 1
                """,
            ),
            _scenario(
                "K007",
                "ranking",
                "单笔金额最大的订单",
                fact,
                [],
                """
                SELECT order_id, ROUND(order_amount, 2) AS order_amount
                FROM fact_order
                ORDER BY order_amount DESC, order_id
                LIMIT 1
                """,
            ),
            _scenario(
                "K008",
                "ranking",
                "平均订单金额最高的会员等级",
                customer,
                ["AOV"],
                """
                SELECT c.member_level, ROUND(AVG(o.order_amount), 2) AS aov
                FROM fact_order o
                JOIN dim_customer c ON o.customer_id = c.customer_id
                GROUP BY c.member_level
                ORDER BY aov DESC
                LIMIT 1
                """,
            ),
            _scenario(
                "K009",
                "ranking",
                "2025年3月销售额最高的品类",
                ["fact_order", "dim_date", "dim_product"],
                ["GMV"],
                """
                SELECT p.category, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_date d ON o.date_id = d.date_id
                JOIN dim_product p ON o.product_id = p.product_id
                WHERE d.year = 2025 AND d.month = 3
                GROUP BY p.category
                ORDER BY gmv DESC
                LIMIT 1
                """,
            ),
            _scenario(
                "K010",
                "ranking",
                "华北销售额前三的商品",
                ["fact_order", "dim_region", "dim_product"],
                ["GMV"],
                """
                SELECT p.product_name, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                JOIN dim_product p ON o.product_id = p.product_id
                WHERE r.region_name = '华北'
                GROUP BY p.product_name
                ORDER BY gmv DESC
                LIMIT 3
                """,
            ),
            _scenario(
                "K011",
                "ranking",
                "哪个品牌销量最高",
                product,
                [],
                """
                SELECT p.brand, SUM(o.order_quantity) AS qty
                FROM fact_order o
                JOIN dim_product p ON o.product_id = p.product_id
                GROUP BY p.brand
                ORDER BY qty DESC
                LIMIT 1
                """,
            ),
            _scenario(
                "K012",
                "ranking",
                "订单金额最低的大区",
                region,
                ["GMV"],
                """
                SELECT r.region_name, ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                GROUP BY r.region_name
                ORDER BY gmv ASC
                LIMIT 1
                """,
            ),
        ]
    )

    scenarios.extend(
        [
            _scenario(
                "Z001",
                "zero",
                "统计2024年的销售总额",
                date,
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_date d ON o.date_id = d.date_id
                WHERE d.year = 2024
                """,
                expect_empty=True,
            ),
            _scenario(
                "Z002",
                "zero",
                "东北地区的销售额是多少",
                region,
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_region r ON o.region_id = r.region_id
                WHERE r.region_name = '东北'
                """,
                expect_empty=True,
            ),
            _scenario(
                "Z003",
                "zero",
                "钻石会员的成交总额",
                customer,
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_customer c ON o.customer_id = c.customer_id
                WHERE c.member_level = '钻石'
                """,
                expect_empty=True,
            ),
            _scenario(
                "Z004",
                "zero",
                "小米品牌卖了多少钱",
                product,
                ["GMV"],
                """
                SELECT ROUND(SUM(o.order_amount), 2) AS gmv
                FROM fact_order o
                JOIN dim_product p ON o.product_id = p.product_id
                WHERE p.brand = '小米'
                """,
                expect_empty=True,
            ),
        ]
    )

    if len(scenarios) != 120:
        raise RuntimeError(f"场景数量必须是 120，实际为 {len(scenarios)}")
    return scenarios
