from stock_data import get_krx_stock_list, get_krx_daily, get_krx_index
print('코스피 지수:', get_krx_index('KOSPI'))
print('삼성전자 5일:', get_krx_daily('005930', 'STK', 5))
print('코스피 종목수:', len(get_krx_stock_list('STK')))
