/* @wireforge afn=03 di=E80403A2 dir=uplink desc="返回节点地理位置信息" */
typedef struct __attribute__((packed)) {
    uint8_t response_count; /* @desc 本次应答的从节点数量 */
    struct {
        node_address_t node_addr; /* @desc 从节点地址 @domain node_address */
        uint8_t longitude[4]; /* @desc 经度(XXXX.XXXX BCD) @alias bcd */
        uint8_t latitude[4]; /* @desc 纬度(XXXX.XXXX BCD) @alias bcd */
        uint8_t altitude[3]; /* @desc 海拔(XXXX.XX BCD) @alias bcd */
    } node_infos[]; /* @count_ref response_count @item_name node_info */
} query_geo_info_resp_t;
