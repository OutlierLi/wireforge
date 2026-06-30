/* @wireforge afn=05 di=E80505A0 dir=uplink desc="上报未识别节点信息" */
typedef struct __attribute__((packed)) {
    uint8_t node_count; /* @desc 上报未识别节点的数量 */
    struct {
        node_address_t node_addr; /* @desc 未识别节点地址 @domain node_address */
        uint8_t device_type; /* @desc 从节点设备类型 */
    } node_infos[]; /* @count_ref node_count @item_name node_info */
} report_unrecognized_node_t;
