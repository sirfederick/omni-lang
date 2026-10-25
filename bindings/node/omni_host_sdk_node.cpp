// Thin N-API projection of the public Omni Host SDK ABI.  It never parses or
// writes OMI1 itself; frames remain opaque Buffers produced/consumed by Core.
#include <node_api.h>

#include <cstdint>
#include <cstring>
#include <string>
#include <vector>

extern "C" {
#include "omni/omni_host_sdk_v1.h"
}

namespace {

constexpr uint32_t ok = OMNI_HOST_SDK_V1_OK;

napi_value nil(napi_env env) { napi_value out; napi_get_undefined(env, &out); return out; }
napi_value failure(napi_env env, uint32_t status) {
    napi_throw_error(env, nullptr, ("omni_host_sdk_v1 status=" + std::to_string(status)).c_str());
    return nil(env);
}
bool args(napi_env env, napi_callback_info info, size_t want, napi_value* values) {
    size_t count = want;
    return napi_get_cb_info(env, info, &count, values, nullptr, nullptr) == napi_ok && count == want;
}
bool u32(napi_env env, napi_value value, uint32_t& out) { return napi_get_value_uint32(env, value, &out) == napi_ok; }
bool handle(napi_env env, napi_value value, uint64_t& out) {
    bool lossless = false;
    return napi_get_value_bigint_uint64(env, value, &out, &lossless) == napi_ok && lossless;
}
napi_value handle_value(napi_env env, uint64_t value) { napi_value out; napi_create_bigint_uint64(env, value, &out); return out; }
bool bytes(napi_env env, napi_value value, uint8_t*& data, uint32_t& size) {
    bool is_buffer = false; void* raw = nullptr; size_t length = 0;
    if (napi_is_buffer(env, value, &is_buffer) != napi_ok || !is_buffer ||
        napi_get_buffer_info(env, value, &raw, &length) != napi_ok || length > UINT32_MAX) return false;
    data = static_cast<uint8_t*>(raw); size = static_cast<uint32_t>(length); return true;
}
bool text(napi_env env, napi_value value, std::string& out) {
    size_t size = 0;
    if (napi_get_value_string_utf8(env, value, nullptr, 0, &size) != napi_ok || size > UINT32_MAX) return false;
    out.resize(size);
    return napi_get_value_string_utf8(env, value, out.data(), size + 1, &size) == napi_ok;
}
napi_value module_open(napi_env env, napi_callback_info info) {
    napi_value values[3]; std::string path; uint8_t *artifact = nullptr, *descriptor = nullptr; uint32_t artifact_size = 0, descriptor_size = 0; uint64_t module = 0;
    if (!args(env, info, 3, values) || !text(env, values[0], path) || !bytes(env, values[1], artifact, artifact_size) || !bytes(env, values[2], descriptor, descriptor_size) || artifact_size != 32 || descriptor_size != 32) return failure(env, 2);
    const auto status = omni_host_sdk_v1_module_open(reinterpret_cast<const uint8_t*>(path.data()), static_cast<uint32_t>(path.size()), artifact, descriptor, &module);
    return status == ok ? handle_value(env, module) : failure(env, status);
}
napi_value module_close(napi_env env, napi_callback_info info) { napi_value values[1]; uint64_t module = 0; if (!args(env, info, 1, values) || !handle(env, values[0], module)) return failure(env, 2); const auto status = omni_host_sdk_v1_module_close(module); return status == ok ? nil(env) : failure(env, status); }
napi_value request_count(napi_env env, napi_callback_info info) { napi_value values[1], out; uint64_t module = 0; uint32_t count = 0; if (!args(env, info, 1, values) || !handle(env, values[0], module)) return failure(env, 2); const auto status = omni_host_sdk_v1_module_request_count(module, &count); napi_create_uint32(env, count, &out); return status == ok ? out : failure(env, status); }
napi_value request_node(napi_env env, napi_callback_info info) { napi_value values[2]; uint64_t module = 0; uint32_t index = 0, node = 0; if (!args(env, info, 2, values) || !handle(env, values[0], module) || !u32(env, values[1], index)) return failure(env, 2); const auto status = omni_host_sdk_v1_module_request_node(module, index, &node); return status == ok ? [] (napi_env e, uint32_t n) { napi_value o; napi_create_uint32(e, n, &o); return o; }(env, node) : failure(env, status); }
napi_value result_node(napi_env env, napi_callback_info info) { napi_value values[1]; uint64_t module = 0; uint32_t node = 0; if (!args(env, info, 1, values) || !handle(env, values[0], module)) return failure(env, 2); const auto status = omni_host_sdk_v1_module_result_node(module, &node); napi_value out; napi_create_uint32(env, node, &out); return status == ok ? out : failure(env, status); }
napi_value node_kind(napi_env env, napi_callback_info info) { napi_value values[2]; uint64_t module = 0; uint32_t node = 0, kind = 0; if (!args(env, info, 2, values) || !handle(env, values[0], module) || !u32(env, values[1], node)) return failure(env, 2); const auto status = omni_host_sdk_v1_schema_node_kind(module, node, &kind); napi_value out; napi_create_uint32(env, kind, &out); return status == ok ? out : failure(env, status); }
napi_value node_typeid(napi_env env,napi_callback_info info){napi_value v[2],out;uint64_t module=0;uint32_t node=0;if(!args(env,info,2,v)||!handle(env,v[0],module)||!u32(env,v[1],node))return failure(env,2);uint8_t* data=nullptr;if(napi_create_buffer(env,32,reinterpret_cast<void**>(&data),&out)!=napi_ok)return nil(env);const auto s=omni_host_sdk_v1_schema_node_typeid(module,node,data);return s==ok?out:failure(env,s);}
napi_value node_label(napi_env env,napi_callback_info info){napi_value v[3],out;uint64_t module=0;uint32_t node=0,index=0,size=0;if(!args(env,info,3,v)||!handle(env,v[0],module)||!u32(env,v[1],node)||!u32(env,v[2],index))return failure(env,2);auto s=omni_host_sdk_v1_schema_node_label_read(module,node,index,nullptr,0,&size);if(s!=6)return failure(env,s);uint8_t* data=nullptr;if(napi_create_buffer(env,size,reinterpret_cast<void**>(&data),&out)!=napi_ok)return nil(env);s=omni_host_sdk_v1_schema_node_label_read(module,node,index,data,size,&size);return s==ok?out:failure(env,s);}
napi_value node_child_count(napi_env env, napi_callback_info info) { napi_value values[2], out; uint64_t module=0; uint32_t node=0,count=0; if(!args(env,info,2,values)||!handle(env,values[0],module)||!u32(env,values[1],node))return failure(env,2); const auto status=omni_host_sdk_v1_schema_node_child_count(module,node,&count); napi_create_uint32(env,count,&out); return status==ok?out:failure(env,status); }
napi_value node_child(napi_env env, napi_callback_info info) { napi_value values[3]; uint64_t module = 0; uint32_t node = 0, index = 0, child = 0; if (!args(env, info, 3, values) || !handle(env, values[0], module) || !u32(env, values[1], node) || !u32(env, values[2], index)) return failure(env, 2); const auto status = omni_host_sdk_v1_schema_node_child(module, node, index, &child); napi_value out; napi_create_uint32(env, child, &out); return status == ok ? out : failure(env, status); }
napi_value value_create(napi_env env, napi_callback_info info) { napi_value values[2]; uint64_t module = 0, value = 0; uint32_t node = 0; if (!args(env, info, 2, values) || !handle(env, values[0], module) || !u32(env, values[1], node)) return failure(env, 2); const auto status = omni_host_sdk_v1_value_create(module, node, &value); return status == ok ? handle_value(env, value) : failure(env, status); }
napi_value value_destroy(napi_env env, napi_callback_info info) { napi_value values[1]; uint64_t value = 0; if (!args(env, info, 1, values) || !handle(env, values[0], value)) return failure(env, 2); const auto status = omni_host_sdk_v1_value_destroy(value); return status == ok ? nil(env) : failure(env, status); }
napi_value scalar_set(napi_env env, napi_callback_info info) { napi_value values[2]; uint64_t value = 0, bits = 0; if (!args(env, info, 2, values) || !handle(env, values[0], value) || !handle(env, values[1], bits)) return failure(env, 2); const auto status = omni_host_sdk_v1_value_scalar_set(value, bits); return status == ok ? nil(env) : failure(env, status); }
napi_value scalar_get(napi_env env, napi_callback_info info) { napi_value values[1]; uint64_t value = 0, bits = 0; if (!args(env, info, 1, values) || !handle(env, values[0], value)) return failure(env, 2); const auto status = omni_host_sdk_v1_value_scalar_get(value, &bits); return status == ok ? handle_value(env, bits) : failure(env, status); }
napi_value value_kind(napi_env env,napi_callback_info info){napi_value v[1],out;uint64_t value=0;uint32_t kind=0;if(!args(env,info,1,v)||!handle(env,v[0],value))return failure(env,2);const auto s=omni_host_sdk_v1_value_kind(value,&kind);napi_create_uint32(env,kind,&out);return s==ok?out:failure(env,s);}
napi_value value_typeid(napi_env env,napi_callback_info info){napi_value v[1],out;uint64_t value=0;if(!args(env,info,1,v)||!handle(env,v[0],value))return failure(env,2);uint8_t* data=nullptr;if(napi_create_buffer(env,32,reinterpret_cast<void**>(&data),&out)!=napi_ok)return nil(env);const auto s=omni_host_sdk_v1_value_typeid(value,data);return s==ok?out:failure(env,s);}
napi_value data_set(napi_env env, napi_callback_info info) { napi_value values[2]; uint64_t value = 0; uint8_t* data = nullptr; uint32_t size = 0; if (!args(env, info, 2, values) || !handle(env, values[0], value) || !bytes(env, values[1], data, size)) return failure(env, 2); const auto status = omni_host_sdk_v1_value_data_set(value, data, size); return status == ok ? nil(env) : failure(env, status); }
napi_value data_get(napi_env env, napi_callback_info info) { napi_value values[1],out; uint64_t value=0; uint32_t size=0; if(!args(env,info,1,values)||!handle(env,values[0],value))return failure(env,2); auto status=omni_host_sdk_v1_value_data_read(value,nullptr,0,&size); if(status!=6)return failure(env,status); uint8_t* data=nullptr; if(napi_create_buffer(env,size,reinterpret_cast<void**>(&data),&out)!=napi_ok)return nil(env); status=omni_host_sdk_v1_value_data_read(value,data,size,&size); return status==ok?out:failure(env,status); }
napi_value discriminant_set(napi_env env,napi_callback_info info){napi_value v[2];uint64_t value=0;uint32_t d=0;if(!args(env,info,2,v)||!handle(env,v[0],value)||!u32(env,v[1],d))return failure(env,2);const auto s=omni_host_sdk_v1_value_discriminant_set(value,d);return s==ok?nil(env):failure(env,s);}
napi_value discriminant_get(napi_env env,napi_callback_info info){napi_value v[1],out;uint64_t value=0;uint32_t d=0;if(!args(env,info,1,v)||!handle(env,v[0],value))return failure(env,2);const auto s=omni_host_sdk_v1_value_discriminant_get(value,&d);napi_create_uint32(env,d,&out);return s==ok?out:failure(env,s);}
napi_value child_count(napi_env env,napi_callback_info info){napi_value v[1],out;uint64_t value=0;uint32_t count=0;if(!args(env,info,1,v)||!handle(env,v[0],value))return failure(env,2);const auto s=omni_host_sdk_v1_value_child_count(value,&count);napi_create_uint32(env,count,&out);return s==ok?out:failure(env,s);}
napi_value child_set(napi_env env,napi_callback_info info){napi_value v[3];uint64_t parent=0,child=0;uint32_t index=0;if(!args(env,info,3,v)||!handle(env,v[0],parent)||!u32(env,v[1],index)||!handle(env,v[2],child))return failure(env,2);const auto s=omni_host_sdk_v1_value_child_set(parent,index,child);return s==ok?nil(env):failure(env,s);}
napi_value child_get(napi_env env,napi_callback_info info){napi_value v[2];uint64_t parent=0,child=0;uint32_t index=0;if(!args(env,info,2,v)||!handle(env,v[0],parent)||!u32(env,v[1],index))return failure(env,2);const auto s=omni_host_sdk_v1_value_child_get(parent,index,&child);return s==ok?handle_value(env,child):failure(env,s);}
napi_value encode(napi_env env, napi_callback_info info) {
    napi_value values[2]; uint64_t module = 0; bool is_array = false; uint32_t count = 0;
    if (!args(env, info, 2, values) || !handle(env, values[0], module) || napi_is_array(env, values[1], &is_array) != napi_ok || !is_array || napi_get_array_length(env, values[1], &count) != napi_ok) return failure(env, 2);
    std::vector<uint64_t> handles(count); for (uint32_t i = 0; i < count; ++i) { napi_value entry; if (napi_get_element(env, values[1], i, &entry) != napi_ok || !handle(env, entry, handles[i])) return failure(env, 2); }
    uint32_t size = 0; auto status = omni_host_sdk_v1_request_encode(module, handles.data(), count, nullptr, 0, &size); if (status != OMNI_HOST_SDK_V1_LIMIT_EXCEEDED) return failure(env, status);
    napi_value out; uint8_t* data = nullptr; if (napi_create_buffer(env, size, reinterpret_cast<void**>(&data), &out) != napi_ok) return nil(env);
    status = omni_host_sdk_v1_request_encode(module, handles.data(), count, data, size, &size); return status == ok ? out : failure(env, status);
}
napi_value decode(napi_env env, napi_callback_info info) { napi_value values[2]; uint64_t module = 0, value = 0; uint8_t* frame = nullptr; uint32_t size = 0; if (!args(env, info, 2, values) || !handle(env, values[0], module) || !bytes(env, values[1], frame, size)) return failure(env, 2); const auto status = omni_host_sdk_v1_result_decode(module, frame, size, &value); return status == ok ? handle_value(env, value) : failure(env, status); }

napi_value init(napi_env env, napi_value exports) {
    const napi_property_descriptor properties[] = {
        {"moduleOpen", nullptr, module_open, nullptr, nullptr, nullptr, napi_default, nullptr}, {"moduleClose", nullptr, module_close, nullptr, nullptr, nullptr, napi_default, nullptr}, {"requestCount", nullptr, request_count, nullptr, nullptr, nullptr, napi_default, nullptr},
        {"requestNode", nullptr, request_node, nullptr, nullptr, nullptr, napi_default, nullptr}, {"resultNode", nullptr, result_node, nullptr, nullptr, nullptr, napi_default, nullptr}, {"nodeKind", nullptr, node_kind, nullptr, nullptr, nullptr, napi_default, nullptr}, {"nodeTypeId", nullptr, node_typeid, nullptr, nullptr, nullptr, napi_default, nullptr}, {"nodeLabel", nullptr, node_label, nullptr, nullptr, nullptr, napi_default, nullptr}, {"nodeChild", nullptr, node_child, nullptr, nullptr, nullptr, napi_default, nullptr},
        {"nodeChildCount", nullptr, node_child_count, nullptr, nullptr, nullptr, napi_default, nullptr}, {"valueCreate", nullptr, value_create, nullptr, nullptr, nullptr, napi_default, nullptr}, {"valueDestroy", nullptr, value_destroy, nullptr, nullptr, nullptr, napi_default, nullptr}, {"valueKind", nullptr, value_kind, nullptr, nullptr, nullptr, napi_default, nullptr}, {"valueTypeId", nullptr, value_typeid, nullptr, nullptr, nullptr, napi_default, nullptr}, {"scalarSet", nullptr, scalar_set, nullptr, nullptr, nullptr, napi_default, nullptr}, {"scalarGet", nullptr, scalar_get, nullptr, nullptr, nullptr, napi_default, nullptr}, {"dataSet", nullptr, data_set, nullptr, nullptr, nullptr, napi_default, nullptr}, {"dataGet", nullptr, data_get, nullptr, nullptr, nullptr, napi_default, nullptr}, {"discriminantSet", nullptr, discriminant_set, nullptr, nullptr, nullptr, napi_default, nullptr}, {"discriminantGet", nullptr, discriminant_get, nullptr, nullptr, nullptr, napi_default, nullptr}, {"childCount", nullptr, child_count, nullptr, nullptr, nullptr, napi_default, nullptr}, {"childSet", nullptr, child_set, nullptr, nullptr, nullptr, napi_default, nullptr}, {"childGet", nullptr, child_get, nullptr, nullptr, nullptr, napi_default, nullptr}, {"requestEncode", nullptr, encode, nullptr, nullptr, nullptr, napi_default, nullptr}, {"resultDecode", nullptr, decode, nullptr, nullptr, nullptr, napi_default, nullptr},
    };
    napi_define_properties(env, exports, sizeof(properties) / sizeof(properties[0]), properties); return exports;
}
} // namespace

NAPI_MODULE(NODE_GYP_MODULE_NAME, init)
