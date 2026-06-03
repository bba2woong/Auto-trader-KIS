def run_backtest(df, params):
    capital = 1_000_000  # 초기 자금
    position = 0
    
    for i, row in df.iterrows():
        signal = strategy(row, params)  # 기존 strategy.py 재사용!
        
        if signal == "BUY" and position == 0:
            position = capital / row["close"]
            
        elif signal == "SELL" and position > 0:
            capital = position * row["close"]
            position = 0
    
    return capital  # 최종 자산