package com.ruanzhu.doorhandle.module.detection.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.ruanzhu.doorhandle.module.detection.entity.DetectionImageFingerprint;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Select;

import java.util.Collection;
import java.util.List;

@Mapper
public interface DetectionImageFingerprintMapper extends BaseMapper<DetectionImageFingerprint> {
    @Select("<script>SELECT * FROM detection_image_fingerprint WHERE sha256 IN <foreach collection='hashes' item='hash' open='(' separator=',' close=')'>#{hash}</foreach></script>")
    List<DetectionImageFingerprint> findBySha256(Collection<String> hashes);
}
