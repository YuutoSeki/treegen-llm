# -*- coding: utf-8 -*-
# 距離は Blender ユニット、角度はラジアンを前提としたスキーマです。
# キー名は Geometry Nodes の「identifier」（例: Socket_44）と一致させてください。
# "description" は LLM に渡す仕様説明として使われます。

USER_SOCKET_SCHEMA = {
    # 幹・枝の長さ
    "Socket_3":  {"description": "幹の全長（根元から先端までの距離）","type": "float","min": 0.0,"max": 40.0,"default": 4.0},
    "Socket_4":  {"description": "第1段の枝の長さ","type": "float","min": 0.0,"max": 40.0,"default": 3.0},
    "Socket_5":  {"description": "第2段の枝の長さ","type": "float","min": 0.0,"max": 40.0,"default": 2.0},
    "Socket_6":  {"description": "第3段の枝の長さ","type": "float","min": 0.0,"max": 40.0,"default": 2.0},
    "Socket_7":  {"description": "第4段の枝の長さ","type": "float","min": 0.0,"max": 40.0,"default": 1.0},
    "Socket_8":  {"description": "第5段の枝の長さ","type": "float","min": 0.0,"max": 40.0,"default": 1.0},

    # カーブの制御点数（細かいほど形状が滑らか／複雑になります）
    "Socket_9":  {"description": "幹カーブの制御点数","type": "integer", "min": 1,"max": 25,"default": 12},
    "Socket_10": {"description": "第1段の枝カーブの制御点数","type": "integer", "min": 1,"max": 20,"default": 8},
    "Socket_11": {"description": "第2段の枝カーブの制御点数","type": "integer", "min": 1,"max": 15,"default": 5},
    "Socket_12": {"description": "第3段の枝カーブの制御点数","type": "integer", "min": 1,"max": 10,"default": 5},
    "Socket_13": {"description": "第4段の枝カーブの制御点数","type": "integer", "min": 1,"max": 5,"default": 3},
    "Socket_14": {"description": "第5段の枝カーブの制御点数","type": "integer", "min": 1,"max": 5,"default": 3},

    # 枝の生える角度（各段ごとの基準角。値が0だと水平になり、大きくなるほど上方向に曲がります）
    "Socket_23": {"description": "第1段の枝の生える角度（-π/2〜+π/2）","type": "float","min": -1.57079,"max": 1.57079,"default": 1.0472},
    "Socket_24": {"description": "第2段の枝の生える角度（0〜π/2）","type": "float","min": 0.0,"max": 1.57079, "default": 1.0472},
    "Socket_25": {"description": "第3段の枝の生える角度（0〜π/2）","type": "float","min": 0.0,"max": 1.57079, "default": 1.0472},
    "Socket_26": {"description": "第4段の枝の生える角度（0〜π/2）","type": "float","min": 0.0,"max": 1.57079, "default": 1.0472},
    "Socket_27": {"description": "第5段の枝の生える角度（0〜π/2）","type": "float","min": 0.0,"max": 1.57079, "default": 1.0472},

    # 幹の太さ
    "Socket_36": {"description": "幹の基部半径","type": "float","min": 0.0,"max": 10,"default": 0.2},

    # --- 葉関連 -------------------------------------------------------------
    # 親ブール：ONで葉を生成、OFFで枝のみ（GN側のスイッチに接続してください）
    "Socket_42": {"description": "葉を有効化（ONで葉を生成／OFFで枝のみ）","type": "bool","default": True},
    # 密度スケール（Multiply側）
    # 最終密度 = Socket_44 × pow( 分布インデックス, Socket_45 )。
    # 値を上げるほど全体の葉量が比例して増える“直倍率”。
    "Socket_44": {"description": "葉の密度スケール（最終密度 = 〈この値〉 × pow(分布インデックス, 密度指数)）","type": "float","min": 0.0,"max": 500.0,"default": 200.0},
    # 密度指数（Power の指数 = ガンマ）
    # 1で線形、1未満で低インデックス側を持ち上げて密になりやすく、1より大きいと抑え気味の分布になる。
    "Socket_45": {"description": "密度指数（ガンマ）：1で線形、1未満は“低域持ち上げ”、1より大きいと“抑え気味”の分布にする","type": "float","min": 0.0,"max": 1.0,"default": 0.5},
    # 葉の生成レベル（分岐階層フィルタ）
    # 指定した階層“以上”の枝にのみ葉を生やします。
    # 1=幹からすべて、2=一次枝から、3=二次枝から、4=三次枝から（既定）、5=四次枝から、6=五次枝のみ
    "Socket_46": {"description": "葉の生成レベル（1〜6）。値以上の分岐階層にのみ葉を生成：1=幹から／2=一次枝から／3=二次枝から／4=三次枝から／5=四次枝から／6=五次枝のみ","type": "integer","min": 1,"max": 6,"default": 4},
    # 葉の縦方向角（基準角）。GNラベル: leaves_vertical_angle
    # 0で水平、プラスで上向き、マイナスで下向き。
    "Socket_47": {"description": "葉の縦方向角（基準角、ラジアン）。0=水平、正で上向き・負で下向き","type": "float","min": -1.57079,"max": 1.57079,"default": -0.349066},
    # 葉の角度のカーブ寄せ角（ラジアン）。GNラベル: leaves_angle_to_curve
    # 0=寄せない、正方向でカーブ方向へ寄せる（必要に応じて符号反転・Mixで実装）。
    "Socket_48": {"description": "葉の角度のカーブ寄せ角（ラジアン）。0=寄せない／±で寄せ量を調整（-π/2〜+π/2）","type": "float","min": -1.57079,"max": 1.57079,"default": 0.785398},
    # 〈新規〉葉の基準スケール（相対倍率）
    "Socket_49": {"description": "葉の基準スケール（相対倍率）。値が大きいほど葉が大きくなる","type": "float","min": 0.01,"max": 5.0,"default": 1.0},      
}