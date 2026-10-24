package com.ruanzhu.doorhandle.module.ai.evolution;

import java.util.*;

/** Exact file digests and bounded line comparison. Large documents retain a side-by-side preview. */
public final class SkillVersionComparison {
    private SkillVersionComparison() {}
    public record Line(String type,Integer oldLine,Integer newLine,String text) {}
    public record View(int fromVersion,int toVersion,String fromCommit,String toCommit,
            List<String> addedFiles,List<String> removedFiles,List<String> changedFiles,
            boolean contentChanged,boolean descriptionChanged,String mode,List<Line> lines,
            Integer addedLines,Integer removedLines,boolean truncated) {}
    public static View compare(SkillDtos.Version before,SkillDtos.Version after){
        var left=files(before.evidence());var right=files(after.evidence());var added=new TreeSet<String>();var removed=new TreeSet<String>();var changed=new TreeSet<String>();
        right.forEach((path,hash)->{if(!left.containsKey(path))added.add(path);else if(!Objects.equals(left.get(path),hash))changed.add(path);});left.keySet().forEach(path->{if(!right.containsKey(path))removed.add(path);});
        String[] a=before.instructions().split("\n",-1),b=after.instructions().split("\n",-1);var lines=new ArrayList<Line>();
        boolean large=(long)a.length*b.length>1000000;Integer insertions=null,deletions=null;
        if(!large){
            int[][] longest=new int[a.length+1][b.length+1];
            for(int i=a.length-1;i>=0;i--)for(int j=b.length-1;j>=0;j--)longest[i][j]=a[i].equals(b[j])?1+longest[i+1][j+1]:Math.max(longest[i+1][j],longest[i][j+1]);
            int i=0,j=0;insertions=0;deletions=0;
            while(i<a.length||j<b.length){
                if(i<a.length&&j<b.length&&a[i].equals(b[j])){i++;j++;}
                else if(j<b.length&&(i==a.length||longest[i][j+1]>=longest[i+1][j])){insertions++;if(lines.size()<200)lines.add(new Line("ADD",null,j+1,b[j]));j++;}
                else{deletions++;if(lines.size()<200)lines.add(new Line("REMOVE",i+1,null,a[i]));i++;}
            }
        }
        return new View(before.version(),after.version(),revision(before.evidence()),revision(after.evidence()),
                List.copyOf(added),List.copyOf(removed),List.copyOf(changed),!before.instructions().equals(after.instructions()),!before.description().equals(after.description()),
                large?"SIDE_BY_SIDE":"LINE_DIFF",List.copyOf(lines),insertions,deletions,large||insertions+deletions>lines.size());
    }
    private static String revision(Map<String,Object> evidence){return Objects.toString(evidence.get("commit"),Objects.toString(evidence.get("sourceVersion"),"未知"));}
    private static Map<String,String> files(Map<String,Object> evidence){
        var result=new LinkedHashMap<String,String>();if(evidence.get("files") instanceof List<?> files)for(var value:files)if(value instanceof Map<?,?> file&&file.get("path") instanceof String path&&file.get("sha256") instanceof String hash)result.put(path,hash);return result;
    }
}
