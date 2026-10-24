package com.ruanzhu.doorhandle.module.ai.evolution;

import java.net.URI;
import java.util.*;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

/** Market links locate content; only a verified Git directory or a native market identity can define upgrade lineage. */
public final class SkillSourcePolicy {
    private SkillSourcePolicy(){}
    public record Source(String provider,String repository,String directory,String name,String ref){}
    public static Source parse(String value){
        try{
            if(value==null||value.length()>1000)throw new IllegalArgumentException();var url=URI.create(value);
            if(!"https".equals(url.getScheme())||url.getQuery()!=null||url.getFragment()!=null||url.getRawPath().contains("%"))throw new IllegalArgumentException();
            String[] parts=url.getRawPath().replaceFirst("^/","").replaceFirst("/$","").split("/",-1);
            if(Arrays.stream(parts).anyMatch(p->p.isEmpty()||p.equals(".")||p.equals("..")))throw new IllegalArgumentException();
            String host=url.getRawAuthority();
            if(Set.of("skills.sh","www.skills.sh").contains(host)&&parts.length==3&&Arrays.stream(parts).allMatch(SkillSourcePolicy::segment))return new Source("SKILLS_SH",(parts[0]+"/"+parts[1]).toLowerCase(Locale.ROOT),null,parts[2],null);
            if(Set.of("modelscope.cn","www.modelscope.cn").contains(host)&&parts.length==3&&parts[0].equals("skills")&&parts[1].startsWith("@")&&segment(parts[1].substring(1))&&parts[2].matches("[a-z][a-z0-9-]{2,63}"))return new Source("MODELSCOPE",parts[1]+"/"+parts[2],null,parts[2],null);
            if(!"github.com".equals(host)||parts.length<5||!parts[2].equals("tree")||!segment(parts[0])||!segment(parts[1])||!segment(parts[3])||Arrays.stream(parts,4,parts.length).anyMatch(p->!segment(p)))throw new IllegalArgumentException();
            return new Source("GITHUB",(parts[0]+"/"+parts[1]).toLowerCase(Locale.ROOT),String.join("/",Arrays.copyOfRange(parts,4,parts.length)),parts[parts.length-1],parts[3]);
        }catch(Exception invalid){throw new ResponseStatusException(HttpStatus.BAD_REQUEST,"请使用公开 GitHub Skill 目录、skills.sh 技能详情或魔搭 Skill 公开链接");}
    }
    private static boolean segment(String value){return value.matches("[A-Za-z0-9_-][A-Za-z0-9_.-]{0,99}");}
    public static String identity(Map<String,Object> manifest){
        String identity;
        if("CONTENT_SNAPSHOT".equals(manifest.get("revisionKind"))){
            var source=parse(Objects.toString(manifest.get("sourceUrl"),""));String hash=Objects.toString(manifest.get("archiveSha256"),"");
            if(!source.provider().equals("MODELSCOPE")||!"MODELSCOPE".equals(manifest.get("provider"))||manifest.get("commit")!=null||!hash.matches("[a-f0-9]{64}")||!("snapshot-sha256:"+hash).equals(manifest.get("sourceVersion"))||!("https://www.modelscope.cn/skills/"+source.repository()+"/archive/zip/master").equals(manifest.get("resolvedUrl")))throw invalid();
            identity="modelscope:"+source.repository();
        }else{
            var source=parse(Objects.toString(manifest.get("resolvedUrl"),""));String commit=Objects.toString(manifest.get("commit"),"");
            if(!source.provider().equals("GITHUB")||!commit.matches("[a-f0-9]{40}")||!commit.equals(source.ref()))throw invalid();
            identity="github:"+source.repository()+"/"+source.directory();
        }
        if(manifest.containsKey("sourceIdentity")&&!identity.equals(manifest.get("sourceIdentity")))throw invalid();return identity;
    }
    public static String revision(Map<String,Object> manifest){identity(manifest);return "CONTENT_SNAPSHOT".equals(manifest.get("revisionKind"))?Objects.toString(manifest.get("sourceVersion")):Objects.toString(manifest.get("commit"));}
    public static void assertUpgradeCandidate(Map<String,Object> previous,String candidate){
        String old=identity(previous);var incoming=parse(candidate);boolean same=switch(incoming.provider()){
            case "GITHUB"->old.equals("github:"+incoming.repository()+"/"+incoming.directory());
            case "SKILLS_SH"->old.startsWith("github:"+incoming.repository()+"/"); // exact directory is checked again after download
            case "MODELSCOPE"->old.equals("modelscope:"+incoming.repository());
            default->false;
        };
        if(!same)throw new ResponseStatusException(HttpStatus.CONFLICT,"升级必须来自同一仓库的同一技能目录或同一原生市场来源；无法证明跨市场同源时请作为新技能安装");
    }
    private static ResponseStatusException invalid(){return new ResponseStatusException(HttpStatus.CONFLICT,"固定来源目录或内容快照无法核对");}
}
