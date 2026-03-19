# -*- coding: utf-8 -*-
"""
===================================
A股自选股智能分析系统 - 分析服务层
===================================

职责：
1. 封装核心分析逻辑，支持多调用方（CLI、WebUI、Bot）
2. 提供清晰的API接口，不依赖于命令行参数
3. 支持依赖注入，便于测试和扩展
4. 统一管理分析流程和配置
"""

import uuid
from typing import List, Optional
import logging # 【新增】引入日志

from src.analyzer import AnalysisResult
from src.config import get_config, Config
from src.notification import NotificationService
from src.enums import ReportType
from src.core.pipeline import StockAnalysisPipeline
from src.core.market_review import run_market_review

logger = logging.getLogger(__name__)

# ==========================================
# 【新增】猎手 2.0 物理风控模块：全局大盘熔断器
# ==========================================
def check_global_circuit_breaker() -> bool:
    """
    检查全市场是否触发极端恐慌（熔断）。
    作用：如果大盘跌停家数/下跌家数极多，返回 True，触发物理硬锁。
    """
    try:
        # TODO: 这里请接入你 src.data_provider 中的真实行情接口
        # 以下为示例逻辑，你可以使用 akshare 等数据源获取真实的涨跌家数
        # 比如：import akshare as ak; data = ak.stock_board_concept_cons_em()
        
        # 假设我们获取到了全市场的数据
        total_stocks = 5000 
        down_stocks = 4700 # 假设这是通过 API 实时获取的真实下跌家数
        
        # 如果下跌家数占比超过 70%（比如超过 3500 家下跌），触发熔断
        drop_ratio = down_stocks / total_stocks if total_stocks > 0 else 0
        
        if drop_ratio > 0.70:
            logger.warning(f"🚨 触发大盘全局熔断！当前下跌比例高达 {drop_ratio:.1%}")
            return True
            
    except Exception as e:
        logger.error(f"检查大盘环境时发生异常: {e}")
        
    return False

# ==========================================

def analyze_stock(
    stock_code: str,
    config: Config = None,
    full_report: bool = False,
    notifier: Optional[NotificationService] = None,
    is_circuit_broken: bool = False  # 【新增】接收熔断状态
) -> Optional[AnalysisResult]:
    """
    分析单只股票
    """
    if config is None:
        config = get_config()
    
    # 创建分析流水线
    pipeline = StockAnalysisPipeline(
        config=config,
        query_id=uuid.uuid4().hex,
        query_source="cli"
    )
    
    # 使用通知服务（如果提供）
    if notifier:
        pipeline.notifier = notifier
    
    # 根据full_report参数设置报告类型
    report_type = ReportType.FULL if full_report else ReportType.SIMPLE
    
    # 运行单只股票分析（让 AI 正常完成它的工作）
    result = pipeline.process_single_stock(
        code=stock_code,
        skip_analysis=False,
        single_stock_notify=False, # 【修改】先不发送通知，等拦截器处理完再发
        report_type=report_type
    )
    
    # ==========================================
    # 【新增】物理拦截：覆写 AI 的过度乐观信号
    # ==========================================
    if result and is_circuit_broken:
        # 假设 AnalysisResult 类中包含 rating(评级), score(分数), summary(结论) 等属性
        # (请根据你 src.analyzer 中 AnalysisResult 的实际属性名调整)
        buy_signals = ["买入", "强烈买入", "BUY", "STRONG_BUY", "加仓"]
        
        # 如果 AI 逆势给出了买入信号，强行按在地上
        if any(signal in str(result).upper() for signal in buy_signals): 
            # 篡改评级与分数
            if hasattr(result, 'rating'):
                result.rating = "观望"
            if hasattr(result, 'score'):
                result.score = min(result.score, 45) # 强行将分数压低到不及格
            
            # 在 AI 报告的最前面加上醒目的血红色警告
            warning_msg = "🚨 **【猎手系统物理拦截】**\n> 极端股灾环境触发熔断！系统已强制撤销该股的买入评级，严禁在恐慌踩踏期接飞刀！\n\n"
            
            if hasattr(result, 'summary'):
                result.summary = warning_msg + result.summary
            elif hasattr(result, 'conclusion'):
                result.conclusion = warning_msg + result.conclusion
                
    # 拦截处理完毕后，再发送通知
    if notifier and result:
        notifier.send_single_analysis(result)
    # ==========================================

    return result

def analyze_stocks(
    stock_codes: List[str],
    config: Config = None,
    full_report: bool = False,
    notifier: Optional[NotificationService] = None
) -> List[AnalysisResult]:
    """
    分析多只股票
    """
    if config is None:
        config = get_config()
    
    # ==========================================
    # 【新增】在批量分析前，仅检查一次大盘状态，节省网络开销
    # ==========================================
    is_circuit_broken = check_global_circuit_breaker()
    
    results = []
    for stock_code in stock_codes:
        # 将熔断状态传递给单只股票分析函数
        result = analyze_stock(stock_code, config, full_report, notifier, is_circuit_broken)
        if result:
            results.append(result)
    
    return results

def perform_market_review(
    config: Config = None,
    notifier: Optional[NotificationService] = None
) -> Optional[str]:
    """
    执行大盘复盘
    """
    if config is None:
        config = get_config()
    
    # 创建分析流水线以获取analyzer和search_service
    pipeline = StockAnalysisPipeline(
        config=config,
        query_id=uuid.uuid4().hex,
        query_source="cli"
    )
    
    # 使用提供的通知服务或创建新的
    review_notifier = notifier or pipeline.notifier
    
    # 调用大盘复盘函数
    return run_market_review(
        notifier=review_notifier,
        analyzer=pipeline.analyzer,
        search_service=pipeline.search_service
    )
