"""数据库 CRUD 演示脚本：完整覆盖增、删、改、查四种操作。

使用方式：
  python db_crud.py demo       # 跑一遍演示
  python db_crud.py count      # 看各表条数
  python db_crud.py top        # 查看入诗最多 Top 地名
"""
import sys
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config import MYSQL, DB_NAME


def conn():
    return pymysql.connect(**MYSQL, database=DB_NAME)


# ---------- C ----------
def add_image(word: str, category: str, sentiment: float) -> int:
    """新增一个意象词（增）。"""
    with conn() as c, c.cursor() as cur:
        cur.execute(
            "INSERT INTO t_image(word, category, sentiment) "
            "VALUES (%s,%s,%s) "
            "ON DUPLICATE KEY UPDATE category=VALUES(category)",
            (word, category, sentiment),
        )
        c.commit()
        return cur.lastrowid


# ---------- R ----------
def count_all() -> dict:
    """统计各表行数（查）。"""
    out = {}
    with conn() as c, c.cursor() as cur:
        for t in ("t_poet", "t_poem", "t_place", "t_image",
                  "t_poem_place", "t_poem_image"):
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            out[t] = cur.fetchone()[0]
    return out


def top_places(limit: int = 10) -> list[tuple]:
    """入诗最多的古地名 Top N（查·联表）。"""
    with conn() as c, c.cursor() as cur:
        cur.execute("""
            SELECT pl.alias, pl.modern, COUNT(pp.poem_id) AS hit
              FROM t_place pl
              LEFT JOIN t_poem_place pp ON pp.place_id = pl.place_id
             GROUP BY pl.place_id
             ORDER BY hit DESC
             LIMIT %s
        """, (limit,))
        return cur.fetchall()


def poet_summary() -> list[tuple]:
    """诗人创作概览（按朝代+流派分组聚合）。"""
    with conn() as c, c.cursor() as cur:
        cur.execute("""
            SELECT dynasty, school, COUNT(*) AS poet_n,
                   SUM(poem_count) AS poem_n
              FROM t_poet
             GROUP BY dynasty, school
             ORDER BY dynasty, poem_n DESC
        """)
        return cur.fetchall()


# ---------- U ----------
def update_poet_school(name: str, school: str) -> int:
    """修正诗人流派（改）。"""
    with conn() as c, c.cursor() as cur:
        n = cur.execute("UPDATE t_poet SET school=%s WHERE name=%s",
                        (school, name))
        c.commit()
        return n


# ---------- D ----------
def delete_image(word: str) -> int:
    """删除某个意象词（删，会级联清掉 t_poem_image 的关联）。"""
    with conn() as c, c.cursor() as cur:
        n = cur.execute("DELETE FROM t_image WHERE word=%s", (word,))
        c.commit()
        return n


# ---------- demo ----------
def demo() -> None:
    print("==[查]== 各表行数：")
    for t, n in count_all().items():
        print(f"  {t:<14} {n}")

    print("\n==[查]== 入诗最多的古地名 Top10：")
    for alias, modern, hit in top_places(10):
        print(f"  {alias:<6}({modern:<6}) 出现 {hit} 次")

    print("\n==[查]== 朝代×流派 创作概览：")
    for dyn, school, pn, pmn in poet_summary():
        print(f"  {dyn} - {school or '未分':<8} 诗人 {pn} 位 / 作品 {pmn} 首")

    print("\n==[增]== 演示插入新意象'蓑衣'（草木类，情感 +0.3）：")
    add_image("蓑衣", "器物", 0.3)
    print("  done.")

    print("\n==[改]== 演示把'李白'流派从'浪漫派'改为'盛唐浪漫派'：")
    n = update_poet_school("李白", "盛唐浪漫派")
    print(f"  影响行数: {n}")

    print("\n==[删]== 演示删除刚插入的意象'蓑衣'：")
    n = delete_image("蓑衣")
    print(f"  影响行数: {n}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] == "demo":
        demo()
    elif sys.argv[1] == "count":
        for t, n in count_all().items():
            print(f"{t:<14} {n}")
    elif sys.argv[1] == "top":
        for alias, modern, hit in top_places(20):
            print(f"{alias:<6}({modern:<6}) {hit}")
    else:
        print("usage: db_crud.py [demo|count|top]")


if __name__ == "__main__":
    main()
