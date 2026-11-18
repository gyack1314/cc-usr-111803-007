# 降雪道路公告与跨区生猪报价归属

现有项目保存道路公告与产地报价的冻结来源响应。transport 核对请求和原文字节，domain 提取来源声明的资料身份，ledger 原子保存版本，view 展示已收资料及待核状态。collection 将来源目录、待收范围与接收进度持久保存，archive 保留已发布视图所引用的资料状态。方向、路段与公告时段共同决定当前线路状态：同一公告只以最新已收版次参与当前判断，解除通知只作用于其声明的方向与时段；每条报价说明列出采用的来源。修订正文未取得时，先前收据不能证明当前方向判断已核实；报价缺少道路公告时保持待核，不能仅由报价变化推断封路；新的判断不改写已发布的历史视图。合成样例不访问外部站点。来源字段见 docs/source-contract.md。

在项目根目录运行：

    python -m unittest discover -s tests -v
    python -m compileall -q capture_service tests
    python -m capture_service.cli inspect data/normal.json

容器运行：docker build -t pork-collection-007 .；docker run --rm pork-collection-007。
