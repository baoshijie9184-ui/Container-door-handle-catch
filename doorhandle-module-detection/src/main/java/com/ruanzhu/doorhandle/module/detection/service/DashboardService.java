package com.ruanzhu.doorhandle.module.detection.service;

import java.util.List;
import java.util.Map;

/**
 * 仪表盘服务接口
 * 提供仪表盘相关的数据服务
 */
public interface DashboardService {

    /**
     * 获取仪表盘统计数据
     * @return 统计数据，包含检测记录总数、人员总数、设备总数、平均漏检率
     */
    Map<String, Object> getStats();

    /**
     * 获取检测记录趋势数据
     * @param timeRange 时间范围：week/month/year
     * @return 趋势数据，包含时间标签和各种检测数据系列
     */
    Map<String, Object> getDetectionTrend(String timeRange);

    /**
     * 获取检测结果分布数据
     * @return 分布数据，包含六类检测结果的数量统计
     */
    Map<String, Object> getDetectionDistribution();

    /**
     * 获取各地区图片采集量统计
     * @return 各地区的采集图片数量
     */
    List<Map<String, Object>> getRegionStats();

    /**
     * 获取模型使用统计
     * @return 各模型的使用次数、检测图片数、平均漏检率
     */
    List<Map<String, Object>> getModelStats();

    /**
     * 获取质检处置统计
     * @return 人工复核后的待处置、已处置、复检以及处置动作分布
     */
    Map<String, Object> getQualityDispositionStats();

    /**
     * 获取质检待办工作量
     * @return 待复核、待处置、需复检、返工、隔离和失败任务队列
     */
    Map<String, Object> getQualityWorkload();
}
