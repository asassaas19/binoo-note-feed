# binoo-note-feed

note（inoue_kikaku）のマガジンRSSから、binoo.jp ホームの STORIES / おしらせ 用JSONを毎朝7時(JST)に生成し、GitHub Pagesで配信する。

- data/news.json … おしらせマガジン（最新5件）
- data/stories.json … 「BiNooのある暮らし」マガジン（最新6件・サムネイル付き）

配信URL: https://asassaas19.github.io/binoo-note-feed/data/news.json / stories.json

テーマ側: Shopifyテーマ sections/binoo-home-notefeed.liquid がページ読み込み時に取得して #journal を書き換える（取得失敗時は固定表示のまま）。
