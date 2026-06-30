/* parser fixture — struct flex array with node_address (no variant DI) */
typedef struct __attribute__((packed)) {
    uint8_t item_count; /* @desc 元素数量 */
    struct {
        node_address_t node_addr; /* @desc 节点地址 @domain node_address */
        uint8_t device_type; /* @desc 设备类型 */
    } items[]; /* @count_ref item_count @item_name item */
} struct_flex_array_sample_t;
