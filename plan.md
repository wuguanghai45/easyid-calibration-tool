
需要实现一个功能， 更新cameraOffsetTheta(°)的飞书表格文档， 

目前已知的参数有， 配置项app_id, app_secret
参数项 知识库云文档 token， obj_type，table_id， view_id
表单的字段S/N* 的某个值

view_id需要用户提供， S/N*需要用户提供


步骤一： 整体工作流程， 需要先试用app_id和app_secret获取自建应用的app_access_token
步骤二： 然后使用获取的自建应用的app_access_token 和云文档token， obj_type(默认wifi)， 获取云文档的具体信息， 主要是获取obj_token
实际测试的curl 
```
curl -i -X GET 'https://open.feishu.cn/open-apis/wiki/v2/spaces/get_node?obj_type=wiki&token=A6lVwYZ2eiaODXkhmTUcqeoGnMg' \
-H 'Authorization: Bearer u-fRGHDFViN118AJA2XCUyjhhg2DyAh0KVX2GymQYw21IZ'
```
返回的消息

```
{
  "code": 0,
  "data": {
    "node": {
      "creator": "ou_143cba742b7e8f703f39d9707598f03c",
      "has_child": false,
      "node_create_time": "1779432812",
      "node_creator": "ou_143cba742b7e8f703f39d9707598f03c",
      "node_token": "A6lVwYZ2eiaODXkhmTUcqeoGnMg",
      "node_type": "origin",
      "obj_create_time": "1779432812",
      "obj_edit_time": "1779434065",
      "obj_token": "WTpUbBKePas3I0sUD7scpzONnuh",
      "obj_type": "bitable",
      "origin_node_token": "A6lVwYZ2eiaODXkhmTUcqeoGnMg",
      "origin_space_id": "7527243737617055772",
      "owner": "ou_143cba742b7e8f703f39d9707598f03c",
      "parent_node_token": "",
      "space_id": "7527243737617055772",
      "title": "（测试数据）产品硬件版本管理表"
    }
  },
  "msg": "success"
}
```

步骤三:  使用步骤二获取的obj_token作为app_token参数 通过查询记录.md 查询具体的数据， 需要输入参数 view_id， S/N*获取具体的数据
参考curl
```
curl -i -X POST 'https://open.feishu.cn/open-apis/bitable/v1/apps/WTpUbBKePas3I0sUD7scpzONnuh/tables/tblFx2XXsAUHK3qm/records/search?user_id_type=user_id' \
-H 'Content-Type: application/json' \
-H 'Authorization: Bearer t-g1045pfDX5GKX4JGSXLCLUME32CC6VET62TVUOWO' \
-d '{
	"automatic_fields": false,
	"field_names": [
		"S/N*",
		"Model*",
		"cameraOffsetTheta(°)"
	],
	"filter": {
		"conditions": [
			{
				"field_name": "S/N*",
				"operator": "is",
				"value": [
					"K17A05AN"
				]
			}
		],
		"conjunction": "and"
	},
	"sort": [
		{
			"desc": true,
			"field_name": "S/N*"
		}
	],
	"view_id": "vewBikWgKP"
}'
```
参考返回的数据

```
{
  "code": 0,
  "data": {
    "has_more": false,
    "items": [
      {
        "fields": {
          "Model*": {
            "link_record_ids": [
              "recvhokg7Vq7gH"
            ]
          },
          "S/N*": [
            {
              "text": "K17A05AN",
              "type": "text"
            }
          ]
        },
        "record_id": "recvjoZ3Zj8jp5"
      }
    ],
    "total": 1
  },
  "msg": "success"
}
```


步骤四: 使用步骤三获取的record_id， 输入参数cameraOffsetTheta(°)对cameraOffsetTheta(°)进行更新

```
curl -i -X PUT 'https://open.feishu.cn/open-apis/bitable/v1/apps/WTpUbBKePas3I0sUD7scpzONnuh/tables/tblFx2XXsAUHK3qm/records/recvjoZ3Zj8jp5' \
-H 'Content-Type: application/json' \
-H 'Authorization: Bearer t-g1045qaJYDJ6ORAYIKICV3O5CCGNTWZBVYXNGJFQ' \
-d '{
	"fields": {
		"cameraOffsetTheta(°)": "0.1"
	}
}'
```

返回消息
```
{
  "code": 0,
  "data": {
    "record": {
      "fields": {
        "cameraOffsetTheta(°)": "0.1"
      },
      "id": "recvjoZ3Zj8jp5",
      "record_id": "recvjoZ3Zj8jp5"
    }
  },
  "msg": "success"
}
```