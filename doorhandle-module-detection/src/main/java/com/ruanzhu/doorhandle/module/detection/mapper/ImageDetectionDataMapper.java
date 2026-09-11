package com.ruanzhu.doorhandle.module.detection.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruanzhu.doorhandle.module.detection.entity.ImageDetectionData;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import java.util.List;

/**
 * 图像检测数据数据访问层接口
 */
@Mapper
public interface ImageDetectionDataMapper extends BaseMapper<ImageDetectionData> {
    /**
     * 查询所有检测数据
     * @return 检测数据列表
     */
    List<ImageDetectionData> selectAll();

    int updateDetectionDataRecord(ImageDetectionData imageDetectionData);
} 
