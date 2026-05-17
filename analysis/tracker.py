"""
个股跟踪模块（预留接口）
后续用于跟踪选股池个股的后续表现，记录 5日/10日/20日实际涨跌幅
"""


def track_selection(stock_df, trade_date):
    """预留：将选股结果写入跟踪表"""
    pass


def get_track_record(code, days=20):
    """预留：查询某只股票的跟踪记录"""
    pass
