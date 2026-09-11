package com.ruanzhu.doorhandle.module.detection.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionWorkUnitImage;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;
import java.util.List;

@Mapper
public interface DetectionWorkUnitImageMapper extends BaseMapper<DetectionWorkUnitImage> {
    @Select("SELECT * FROM detection_work_unit_image WHERE work_unit_id = #{workUnitId} ORDER BY id")
    List<DetectionWorkUnitImage> findByWorkUnitId(String workUnitId);
}
