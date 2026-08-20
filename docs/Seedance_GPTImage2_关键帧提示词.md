# Seedance × GPT Image 2 关键帧提示词

用于先生成 Seedance 的首帧与尾帧参考图。图像模型只负责静态画面，视频运动由 Seedance 完成。

来源说明：S14、S25、S31 可与当前 `docs/Seedance_开卷视频生成清单.md` 的正式 prompt 逐项核对；S07、S21、S22 的旧轮次原文不在当前工作区，以下为依据已确认的页面用途与场景名重建的关键帧 prompt，不冒充旧版逐字稿。

## 统一视觉约束

- 画幅 16:9，目标输出 2048×1152，横屏网页背景。
- 温润米白宣纸、细纸纤维、低饱和水墨淡彩；墨黑、灰青、松绿、少量赭金或朱砂。
- 构图边缘成景，中间或右侧保留稳定的 HTML 文字安全区。
- 无文字、无汉字、无书法、无题款、无印章、无 Logo、无水印、无边框。
- 无现代物件、无清晰人物脸部、无写实 3D、无卡通、无霓虹、无高饱和、无强闪烁。
- 尾帧保持与首帧同一机位、透视、山形、河道位置、纸纹尺度和曝光，只改变该场景指定的一个主要动势。

## S14｜彩云白帝·轻舟万山

### 首帧

```text
Use case: stylized-concept, Seedance opening keyframe.
Asset type: 16:9 web background keyframe, 2048x1152.
Primary request: 生成一幅可作为诗词网页视频首帧的中国写意水墨山水。
Scene: 清晨夔州白帝城，白帝城只作为左上方极小的淡墨轮廓，长江从万重青灰峡山中向远处纵深展开，一叶极小的无人物轻舟刚从左下雾中出现。
Composition: 镜头固定超广角；峡山、江面和舟集中在左侧与下方；右侧约35%是均匀的浅米色宣纸留白，任何景物都不得进入，供网页叠加诗句。
Style: 温润宣纸纤维，低饱和墨青、灰绿、少量冷白晨光，古雅、克制、宁静，不是旅游宣传画。
Lighting: 雾中微亮的清晨天光，曝光稳定，水面只有极细的墨色反光。
Constraints: 画面像动画的第一秒，所有形体清晰但运动尚未发生；保持大留白和低细节。
Avoid: 任何可读文字、书法、印章、Logo、水印、现代建筑、清晰人物、人物脸、写实摄影、3D塑料感、艳色、镜头倾斜、复杂鸟群、留白区污染。
```

### 尾帧

```text
Use case: stylized-concept, Seedance closing keyframe.
Asset type: 16:9 web background keyframe, 2048x1152.
Input image: the S14 opening keyframe is the continuity reference; preserve its composition and geometry.
Primary request: 在完全相同的固定机位与构图中生成 S14 的尾帧。保留左上淡墨白帝城、同一组峡山轮廓、同一条江道和右侧35%的纯净宣纸留白。
Change: 轻舟移动到左下至中央偏左的位置，舟后出现一条极细的飞白水痕；江面薄雾略向后退，远山层次稍微显出，但不改变山形，不改变季节，不新增主体。
Style: 温润宣纸纤维，低饱和墨青、灰绿、冷白晨光，连续、克制、可由 Seedance 平滑补间。
Constraints: 尾帧仍是静止画面，不要画运动线或速度字样；右侧净区必须保持均匀浅米色、无物体穿越；首尾曝光和纸纹一致。
Avoid: 文字、汉字、书法、印章、Logo、水印、现代物件、清晰人物、山体重构、河道移动、强浪、强光、镜头变化、写实3D、艳色、留白区污染。
```

## S07｜云隐庐山·一山万相

### 首帧

```text
Use case: minimalist-mood-scene, Seedance opening keyframe.
Asset type: 16:9 web background keyframe, 2048x1152.
Primary request: 生成一幅置身庐山云海的极简水墨首帧，用“一座山从不同视角显出不同形态”表达项目的多页面观看方式。
Scene: 左侧近景有一小段湿润崖石与松枝，中景横岭藏在薄雾中，远处只露出一枚淡淡孤峰；不是地理导览图，不出现具体地名或地图线。
Composition: 固定机位，主体全部位于左侧与下方；右侧约38%保持干净、低对比、稳定的米白宣纸净区，供 HTML 标题与数据说明。
Style: 淡墨、灰青、松绿极少点色，纸纹细腻，留白至少40%，安静而有层次。
Lighting: 云海前的柔和散射光，低对比，无戏剧光。
Avoid: 文字、汉字、书法、印章、Logo、水印、地图边界、人物、建筑、强黑墨、艳色、强风、镜头旋转、山体细节过密、净区污染。
```

### 尾帧

```text
Use case: minimalist-mood-scene, Seedance closing keyframe.
Input image: the S07 opening keyframe is the continuity reference; preserve the exact camera, mountain silhouette, paper texture and right-side safe zone.
Primary request: 生成同一庐山云海构图的尾帧，只让云雾错开一层，露出同一座远峰的另一面和一条很淡的山脊，不移动山体，不增加新山峰。
Change: 近景松枝位置不变，雾层从左向右轻轻退开；中景横岭变为侧峰的含蓄轮廓；右侧约38%仍是纯净浅米色宣纸，无任何雾或景物进入。
Style: 低饱和水墨、柔和散射光、纸纹静止、极慢呼吸感，尾帧可与首帧平滑往返。
Avoid: 文字、汉字、书法、印章、Logo、水印、人物、地图线、山体融化重构、强对比、黑墨泼洒、镜头移动、净区污染。
```

## S21｜九州待晓

### 首帧

```text
Use case: stylized-concept, Seedance opening keyframe.
Asset type: 16:9 web background keyframe, 2048x1152.
Primary request: 生成一幅抽象山河长卷式水墨首帧，服务《诗行万里》的全量诗歌、行旅节点和意象数据总入口。
Scene: 右侧约三分之二是淡墨山河、河流和平原的抽象长卷，不画可辨认的行政地图，不出现疆界或文字；一条尚未闭合的细墨行迹从远山向江面延伸，像诗人的行旅轨迹。
Composition: 左侧和中央偏左保留40%左右温润浅宣纸留白，供网页标题与数据；山河只在右侧和下方低对比出现。
Style: 宋版书页般的淡墨、灰青、少量赭金晨光，纸纤维清晰，宏阔但克制，不做战争海报。
Lighting: 天际尚未完全亮起，右上有极轻的晨光，整体曝光稳定。
Avoid: 文字、汉字、书法、印章、Logo、水印、真实国界、地图标签、军队、武器、血腥、现代建筑、强烈政治符号、艳色、黑墨满屏、净区污染。
```

### 尾帧

```text
Use case: stylized-concept, Seedance closing keyframe.
Input image: the S21 opening keyframe is the continuity reference; preserve the same abstract terrain, river positions, camera and paper grain.
Primary request: 生成同一幅山河长卷的尾帧。山河轮廓和抽象地形不得改变，只让未闭合的细墨行迹向前延伸一小段，河面增加一条极淡的反光，天际比首帧亮半级。
Composition: 右侧山河仍然低对比；左侧和中央偏左约40%的浅宣纸文字安全区保持完全干净；不新增版图形状，不出现任何标签。
Style: 宋版书页、水墨淡彩、灰青与米白为主，晨光只作极少赭金点亮，静态而可平滑补间。
Avoid: 文字、汉字、书法、印章、Logo、水印、行政边界、地图标注、战争、人物、现代物件、地形重构、河流改道、强光、艳色、净区污染。
```

## S25｜长安旧梦·夜郎江影

### 首帧

```text
Use case: stylized-concept, Seedance opening keyframe.
Asset type: 16:9 web background keyframe, 2048x1152.
Primary request: 生成现实与旧梦叠影的水墨首帧，表现诗人身在流放江夜、心回长安旧梦。
Scene: 冷青江水横贯下方，左下只有一叶孤舟残影，远山和细雨沉入夜色；水面深处刚刚出现一点极淡的暖金灯影，暗示旧梦尚未完全浮现。
Composition: 右侧35%始终是低纹理浅宣纸净区，供网页诗句；主体集中左侧与下方，画面不要出现清晰人物或面孔。
Style: 古雅水墨淡彩、宣纸纤维、冷青与少量暖金对照，情绪深但不悲惨，像一张电影开场静帧。
Lighting: 冷月低照，暖金只在水中一点点渗出，曝光连续。
Avoid: 文字、汉字、书法、印章、Logo、水印、清晰人物、脸、现代器物、宫殿特写、霓虹、高饱和、写实3D、净区污染。
```

### 尾帧

```text
Use case: stylized-concept, Seedance closing keyframe.
Input image: the S25 opening keyframe is the continuity reference; preserve the same river, boat, distant mountains and right-side 35% safe zone.
Primary request: 生成同一江夜构图的尾帧，让长安旧梦在水面和薄雾中短暂显影后又将要散去。
Change: 冷青江面与孤舟位置不变；左中部叠出极淡的暖金花柳、模糊飞檐、酒杯流光和一笔金鞭弧光，像倒影而不是实体建筑；暖影边缘已经被江风吹散。
Style: 水墨淡彩、冷青底、克制暖金，宣纸纹理连续，人物只能是不可辨认的衣袂墨痕，不出现面孔。
Constraints: 右侧35%净区完全干净；尾帧不改变镜头、不新增真实地标、不制造历史考据错误；可供 Seedance 以叠影方式补间。
Avoid: 文字、汉字、书法、印章、Logo、水印、清晰人物、五官、现代物件、霓虹、强金光、硬切、镜头跳动、净区污染。
```

## S22｜河岳南望

### 首帧

```text
Use case: minimalist-mood-scene, Seedance opening keyframe.
Asset type: 16:9 web background keyframe, 2048x1152.
Primary request: 生成一个方向凝视主题的水墨首帧，服务诗人“望”字的方向罗盘页面。
Scene: 右侧远处是黄河的淡墨弯流与一组抽象高山墨峰，山河不必对应精确地图；薄雾覆盖河岳，南方天际尚未亮起。
Composition: 中央偏左约38%保持温润浅宣纸净区，供玫瑰图和标题；山河退到右侧边缘与下方，低细节、低对比。
Style: 灰青、墨黑、极少赭金，宣纸纤维稳定，宏阔而沉静，不画人物。
Lighting: 远处极淡的南向晨光穿过雾层，整体平光。
Avoid: 文字、汉字、书法、印章、Logo、水印、地图标签、行政边界、人物、建筑特写、强光、艳色、山河移动、净区污染。
```

### 尾帧

```text
Use case: minimalist-mood-scene, Seedance closing keyframe.
Input image: the S22 opening keyframe is the continuity reference; preserve the same river bend, mountain silhouettes, camera and left-center safe zone.
Primary request: 生成同一河岳南望构图的尾帧，只改变光雾：南向天际微亮，河面出现一条细而柔和的暖色反光，雾层稍微退开但不移动山峰和河道。
Composition: 中央偏左约38%继续保持干净浅宣纸；暖色反光只在右下河面，不能进入图表区域。
Style: 低饱和水墨、米白、灰青、极少赭金，安静、连续、可往返循环。
Avoid: 文字、汉字、书法、印章、Logo、水印、真实地图边界、地名、人物、建筑、强太阳光、金色大片、镜头变化、净区污染。
```

## S31｜雪泥鸿爪

### 首帧

```text
Use case: minimalist-mood-scene, Seedance opening keyframe.
Asset type: 16:9 web background keyframe, 2048x1152.
Primary request: 生成“痕迹与识别”主题的水墨首帧，作为诗人字词指纹页面的背景。
Scene: 雪后浅泥横陈，薄雪几乎覆盖所有痕迹，远处只有一只极淡的鸿影即将离开画面；不画近距离鸟身，不画人物。
Composition: 地面和微风卷雪集中左下，右上约35%保持低纹理浅宣纸净区，供网页字卡与统计数据。
Style: 灰白、淡墨、极少冷青，留白克制，像一枚尚未显现的文字指纹。
Lighting: 冬日漫射光，亮度稳定，雪面不刺眼。
Avoid: 文字、汉字、书法、印章、Logo、水印、清晰鸟形、人物、卡通、艳色、现代物件、镜头移动、净区污染。
```

### 尾帧

```text
Use case: minimalist-mood-scene, Seedance closing keyframe.
Input image: the S31 opening keyframe is the continuity reference; preserve the same low camera, snow line, mud texture and upper-right safe zone.
Primary request: 生成同一雪泥构图的尾帧。远鸿已经离开画面，浅雪被风轻轻掀开，在左下至中央偏左自然露出三至四枚清晰但不夸张的鸿爪痕。
Change: 只增加爪痕与少量雪粉，地面透视、光线、构图和右上35%净区完全不变；爪痕要像自然偶然留下的痕迹，不要排列成文字或符号。
Style: 灰白宣纸、淡墨、极少冷青，静谧、克制、可由 Seedance 平滑生成风雪过程。
Avoid: 文字、汉字、书法、印章、Logo、水印、清晰飞鸟、鸟形畸变、人物、卡通、艳色、强风暴雪、镜头变化、净区污染。
```
