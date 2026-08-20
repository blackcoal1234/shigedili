# Seedance × GPT Image 2 关键帧提示词 · 第二批

本批场景：S04、S19、S38、S17、S16、S42。每幕生成首帧后，再以首帧作为编辑参考生成尾帧，供 Seedance 做 8 秒、16:9 的图生视频。

## 生成状态（2026-08-20）

- 已使用 Codex 账号原生图像模型生成完毕；未使用自定义中转、旧 API 地址或旧密钥。
- 正式成品共 12 张，均为 1672×941、16:9 PNG，首尾帧各 6 张。
- 成品目录：`C:\Users\ASUS\Downloads\诗行万里_seedance_keyframes_batch2_20260820`
- S38 首帧曾因月相偏圆进行一次局部校正；被替换试稿保留在成品目录的 `alternates` 子目录，不属于正式 12 张。

统一约束：温润宣纸纤维、低饱和水墨淡彩、固定机位、无任何可读文字/汉字/书法/题款/印章/Logo/水印/边框；无现代物件、清晰人物脸、写实 3D、卡通、霓虹、高饱和；HTML 文字安全区必须保持干净、亮度与纸纹稳定。

## S04｜残城春深

### 首帧

```text
Use case: stylized-concept, Seedance opening keyframe.
Asset type: 16:9 web background keyframe, 1536x864 or larger.
Primary request: 生成一幅克制苍凉、仍有春日生命力的东方水墨首帧。
Scene: 固定远景，画面右侧是被岁月侵蚀的古城墙、半掩城门与淡墨远山，裂隙间深绿春草和藤蔓轻生；墙角探出一枝淡红春花，露珠完整悬在花瓣边；枝头一只极小、自然的孤鸟静栖，不出现人物和战斗。
Composition: 左侧约38%始终是温润浅米色宣纸留白，低对比、无草叶、花瓣、鸟和墨迹进入，供 HTML 诗句叠加；主体集中右侧和下方。
Style: 旧宣纸肌理，灰青、墨黑、极少淡红，晨雾轻薄，古雅而不做灾难大片。
Lighting: 柔和清晨散射光，曝光均匀，露珠不闪耀。
Constraints: 作为动画第一秒，雾、草、花、鸟都接近静止；裂墙结构清楚但不夸张。
Avoid: 文字、书法、印章、Logo、水印、军队、兵器、火焰、尸体、血腥、现代建筑、鸟群复制、鸟形畸变、珠宝般露珠、裂墙增殖、净区污染。
```

### 尾帧

```text
Use case: stylized-concept, Seedance closing keyframe.
Input image: S04 opening keyframe as continuity reference and edit target; preserve the same wall, gate, mountain silhouette, flower, bird and left-side safe zone.
Primary request: 生成同一固定远景的尾帧，只做极轻微的清晨呼吸变化。
Change: 草梢略向同一方向倾斜，花瓣和墙体位置不变；露珠沿花瓣下移一点但仍保持自然小水滴，不要坠落；孤鸟继续停在原枝上，只略微收拢翅膀；晨雾薄一层退开。
Constraints: 左侧约38%浅宣纸净区完全不变；不改变城墙裂隙、河山轮廓、季节和光线；尾帧静止、可由 Seedance 平滑补间。
Avoid: 起飞的鸟、多个鸟、翅膀畸变、露珠变成宝石、墙体融化、藤蔓爆长、战争场面、文字、汉字、书法、印章、Logo、水印、现代物件、强对比、净区污染。
```

## S19｜缺月疏桐·缥缈孤鸿

### 首帧

```text
Use case: minimalist-mood-scene, Seedance opening keyframe.
Asset type: 16:9 web background keyframe, 1536x864 or larger.
Primary request: 生成清冷但柔和的宋代夜庭水墨首帧，表现独处而不惊悚。
Scene: 右上是一弯缺月，三两根稀疏梧桐枝从右缘斜入；右下远山、空庭和薄雾融成淡墨；月下偏右有一只极远、完整、单独的淡墨孤鸿剪影，不出现具体人物。
Composition: 左侧约40%始终是暖白宣纸净区，树枝、月光、孤鸿和墨迹不得进入，供 HTML 诗句；主体只在右侧。
Style: 淡灰、暖白、少量冷青，纸纹细腻，低对比，静谧、悠远。
Lighting: 缺月柔光穿过薄云，曝光稳定，不出现月晕闪烁。
Avoid: 文字、书法、印章、水印、边框、人物、人影、鬼影、血色、惊悚元素、多只飞鸟、鸟形畸变、满树枝叶、月相改变、现代物件、净区污染。
```

### 尾帧

```text
Use case: minimalist-mood-scene, Seedance closing keyframe.
Input image: S19 opening keyframe as continuity reference and edit target; preserve the exact crescent moon, sparse branches, mountain silhouette and left-side safe zone.
Primary request: 生成同一夜庭构图的尾帧，只让空气和孤鸿发生微小变化。
Change: 孤鸿沿原方向横移约一个翼长并略微展翼，仍然只有一只且保持远小比例；一缕薄云轻轻偏过月边；梧桐枝、月相、远山和空庭位置完全不变。
Constraints: 左侧约40%净区保持暖白、无雾无枝无鸟；尾帧低对比、静止、可平滑往返。
Avoid: 鸟复制、鸟身重构、翅膀融化、鸟飞到近景、月亮增殖或变圆、枝条生长、人物剪影、文字、书法、印章、Logo、水印、闪烁、净区污染。
```

## S38｜黄河金樽

### 首帧

```text
Use case: stylized-concept, Seedance opening keyframe.
Asset type: 16:9 web background keyframe, 1536x864 or larger.
Primary request: 生成雄浑但克制的水墨首帧，表现大河、冷月与金樽的夸张尺度。
Scene: 嵩山山居远景，黄河像一幅宽阔的淡墨水势从云天方向向远海铺展，但首帧河面较平静；远处云墨已经定型；一轮冷月半隐于中上方；近景左下或下中放一只比例自然、形体完整的古朴金樽，只有低亮金色反光。
Composition: 右上约38%保持低纹理、亮度稳定的浅宣纸 HTML 净区；河流、月、金樽集中左侧和下方，不进入净区。
Style: 水墨宣纸、墨黑、灰青、少量赭金，豪迈来自尺度而非高饱和或爆炸效果。
Lighting: 冷月清辉，金樽只接住一线柔光，曝光稳定。
Avoid: 文字、书法、印章、Logo、水印、宴饮人群、清晰人物、现代建筑、海啸、瀑布重构、金樽变形、多个杯子、霓虹、过曝金光、净区污染。
```

### 尾帧

```text
Use case: stylized-concept, Seedance closing keyframe.
Input image: S38 opening keyframe as continuity reference and edit target; preserve the same river course, cloud silhouette, moon position, goblet geometry and upper-right safe zone.
Primary request: 生成同一河岳构图的尾帧，只让水纹与金樽反光略微增强。
Change: 河道和远海位置完全不变，水面纹理向下错开一层，云墨边缘略有呼吸；金樽反光比首帧亮半级，月仍是同一枚半隐冷月；不把河面变成巨瀑或海浪。
Constraints: 右上约38%净区保持浅宣纸、无水纹无金光；尾帧静止、连续、适合 Seedance 补间。
Avoid: 河流改道、海啸、瀑布坠落、月亮复制、金樽口沿/把手变形、宴饮人物、文字、汉字、书法、印章、Logo、水印、强光、过饱和、净区污染。
```

## S17｜古原一息·枯荣轮回

### 首帧

```text
Use case: minimalist-mood-scene, Seedance opening keyframe.
Asset type: 16:9 web background keyframe, 1536x864 or larger.
Primary request: 生成表现时间与生命轮回的低机位水墨首帧。
Scene: 地平线压在下三分之一，远原隐入浅墨；下部和右侧是淡赭枯草与少量焦痕；右下或下中只有一线很小、暗朱色的余烬，没有冲天火焰；焦痕旁尚未出现明显嫩芽。
Composition: 左上约40%始终保留浅米色素纸留白，明暗与纸纹稳定，主体不得侵入，供 HTML 诗句；画面低重心、空旷。
Style: 熟宣纸纤维、水墨写意、淡赭、灰墨、极少暗朱，生命力内敛而非灾难感。
Lighting: 柔和阴天光，余烬不发强光，烟只是一缕淡墨。
Avoid: 文字、书法、印章、Logo、水印、人物、动物、建筑、冲天烈焰、爆炸、浓烟、灾难感、写实CG、霓虹、草地满屏变绿、净区闪烁。
```

### 尾帧

```text
Use case: minimalist-mood-scene, Seedance closing keyframe.
Input image: S17 opening keyframe as continuity reference and edit target; preserve the same horizon, dry-grass silhouette, scorch mark and upper-left safe zone.
Primary request: 生成同一枯原构图的尾帧，以极小变化暗示“野火烧不尽、春风吹又生”。
Change: 暗朱余烬变得更暗，焦痕旁只出现两三枚短小嫩芽，附近一小撮草尖略带青色；远原、地平线、枯草大面积色调和纸纹完全不变。
Constraints: 左上约40%净区完全干净；尾帧不得出现整片草地变绿、火焰重燃或大量芽苗，静止且可平滑补间。
Avoid: 大火、浓烟、爆炸、草色融化、嫩芽爆发式生长、地平线漂移、人物、动物、建筑、文字、汉字、书法、印章、Logo、水印、净区污染。
```

## S16｜浣花春夜·江船孤火

### 首帧

```text
Use case: stylized-concept, Seedance opening keyframe.
Asset type: 16:9 web background keyframe, 1536x864 or larger.
Primary request: 生成唐代成都浣花草堂春夜的低饱和水墨首帧，适合作为“可听的诗”页面雨声背景。
Scene: 深灰雨夜，远山、野径和浓云融成沉静墨黑；右下是草堂竹影与溪岸，远处江船只有一豆稳定的暖橙灯火；雨线很少、细柔，溪面近乎平静。
Composition: 左侧约45%为均匀深灰淡墨 HTML 安全留白，无枝叶、船火、强反光和雨线进入；主体低重心在右下与远景。
Style: 宣纸水墨、墨黑、灰青、极少暖橙，听觉联想来自留白与细节，不做戏剧暴雨。
Lighting: 灯火不过曝，云雨漫射光，整体曝光连续。
Avoid: 文字、书法、印章、题款、水印、人物特写、现代物件、闪电、强反光、雨滴贴镜、船或草堂漂移、闪烁、净区污染。
```

### 尾帧

```text
Use case: stylized-concept, Seedance closing keyframe.
Input image: S16 opening keyframe as continuity reference and edit target; preserve the same hut, bamboo silhouette, stream, boat position and left-side safe zone.
Primary request: 生成同一浣花春夜构图的尾帧，只让雨声和水面有轻微增强。
Change: 右侧雨线略密一层，溪面增加少量细小涟漪，远处江船灯火最多亮半级并保持原大小；竹影只轻微倾斜，草堂、山路和云层轮廓不变。
Constraints: 左侧约45%深灰淡墨净区仍无移动纹理；尾帧不出现闪电、强反光或暴雨，静止、连续、适合 Seedance 补间。
Avoid: 雨线铺满画面、雨滴贴镜、灯火膨胀、船体变形、竹叶复制、文字、汉字、书法、印章、Logo、水印、现代物件、闪烁、净区污染。
```

## S42｜潮信海深

### 首帧

```text
Use case: stylized-concept, Seedance opening keyframe.
Asset type: 16:9 web background keyframe, 1536x864 or larger.
Primary request: 生成暮海与双灯倒影的水墨首帧，服务“唐宋意象潮汐”页面。
Scene: 暮海横卷，左右两岸各有一盏遥远的暖色灯，两盏灯位置固定且只有两盏；潮面低平，双重倒影短而分离，刚向海心延伸；幽蓝、淡墨与微金交织。
Composition: 上方约38%是稳定素白宣纸 HTML 净区，无灯光、浪花、反光或墨迹进入；海面和岸线集中下方。
Style: 水墨淡彩、宣纸纤维、低对比、关系感强，不画人物和实体海浪。
Lighting: 暮色平光，灯火柔和不闪烁，倒影细窄。
Avoid: 文字、书法、印章、Logo、水印、人物、巨浪、海啸、灯光增殖、倒影交叉融合、地平线弯曲、过饱和、净区污染。
```

### 尾帧

```text
Use case: stylized-concept, Seedance closing keyframe.
Input image: S42 opening keyframe as continuity reference and edit target; preserve the same two shore lamps, coastline, horizon and upper safe zone.
Primary request: 生成同一暮海构图的尾帧，只让潮线和两条倒影发生小幅关系变化。
Change: 潮线轻抬一层，两条倒影各自延长并略微向海心靠近，但仍然互不相交、不融合成实体；两盏灯、岸线和地平线位置完全不变。
Constraints: 上方约38%素白净区完全稳定；尾帧保持幽蓝淡墨微金，不能变成巨浪或强烈海上日出，适合 Seedance 平滑往返。
Avoid: 灯增殖、倒影交叉、倒影变成人或船、巨浪、海啸、地平线漂移、文字、汉字、书法、印章、Logo、水印、强闪烁、过饱和、净区污染。
```
