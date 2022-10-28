# aws-ec2-ssh

## 概要
- [aws-ec2-sshツール](https://github.com/widdix/aws-ec2-ssh)でIAMユーザーを同期しssh接続する
- GoogleAuthenticatorでMFA認証とする
- Proxyはnginxが動作する
- ポート22番または80番が応答しない場合、起動中のインスタンスがlambdaにより終了され、AutoScalingにて新規インスタンスが起動する

<img src=diagram.png width="760px">

<BR>

## IAMグループとユーザーの作成
- 同期対象とするグループとユーザーを作成
- ユーザーにはssh接続に利用する公開鍵を設定する

<BR>

## VPCの作成
- 設定は任意
- パブリックサブネットを含むこと

<BR>

## EIPの作成
- AutoScalingで起動するEC2にアタッチするためのEIPを作成
- リージョン内で1つだけ作成すること（リージョン内でアタッチ可能なIPを取得するため）

<BR>

## IAMロールの作成
EC2用とLambda用を作成
<details>

- EC2用ポリシー
  <pre>
  {
      "Version": "2012-10-17",
      "Statement": [
          {
              "Effect": "Allow",
              "Action": [
                  "iam:ListSSHPublicKeys",
                  "iam:GetSSHPublicKey"
              ],
              "Resource": [
                  "arn:aws:iam::[AWSアカウントID]:user/*",
                  "arn:aws:iam::[AWSアカウントID]:group/*"
              ]
          },
          {
              "Effect": "Allow",
              "Action": [
                  "iam:ListUsers",
                  "iam:GetGroup"
              ],
              "Resource": "*"
          },
          {
              "Effect": "Allow",
              "Action": [
                  "ec2:DescribeTags",
                  "ec2:DescribeInstances",
                  "ec2:DescribeAddresses",
                  "ec2:AssociateAddress"
              ],
              "Resource": "*"
          },
          {
              "Effect": "Allow",
              "Action": "elasticfilesystem:*",
              "Resource": "arn:aws:elasticfilesystem:*:[AWSアカウントID]:file-system/*"
          },
          {
              "Effect": "Allow",
              "Action": "ssmmessages:*",
              "Resource": "*"
          }
      ]
  }
  </pre>

- Lambda用ポリシー
  <pre>
  {
      "Version": "2012-10-17",
      "Statement": [
          {
              "Sid": "VisualEditor0",
              "Effect": "Allow",
              "Action": [
                  "sns:Publish",
                  "ec2:DescribeInstances",
                  "ec2:DescribeInstanceStatus",
                  "ec2:TerminateInstances"
              ],
              "Resource": "*"
          }
      ]
  }
  </pre>
</details>


<BR>

## セキュリティグループの作成
EC2用とEFS用を作成
<details>


- EC2用
  | プロトコル | ポート | ソース |
  | --- | --- | --- |
  | HTTP |  80  | any　　　　　　　　　　　　　|
  | SSH  |  22  | any　　　　　　　　　　　　 |

- EFS用
  | プロトコル | ポート | ソース |
  | --- | --- | --- |
  | NFS  | 2049 |EC2用セキュリティグループのID |
</details>

<BR>

## EFSの作成
- 管理コンソールにて任意の設定で作成
- EFS用セキュリティグループをアタッチする
- 作成したEFSのIDを控えておく

<BR>

## キーペアの作成
- EC2接続時に使用するキーペアを作成する

<BR>

## AMIの作成
<details>

- EC2インスタンス起動
  - 作成したキーペアを設定
  - 作成したEC2用ロールを設定

- ssh接続
- モジュールインストール
  <pre>
  $ sudo -s
  # yum update -y
  # amazon-linux-extras install -y epel
  # yum install -y git nginx google-authenticator qrencode-libs jq amazon-efs-utils
  </pre>

- nginx起動設定
  <pre>
  # systemctl start nginx.service
  # systemctl status nginx.service
    "active(running)"であること
  # systemctl enable nginx.service
  # systemctl list-unit-files | grep nginx
    "enabled"であること
  </pre>

- AWS CLI v2 インストール
  <pre>
  # curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
  # unzip awscliv2.zip
  # ./aws/install
  # aws --version
    v2であること
    v1の場合は以下のコマンドを実施
    # ln -s -f /usr/local/bin/aws /bin/aws
  </pre>

- sshd 設定
  <pre>
  # cp -p /etc/ssh/sshd_config sshd_config.org
  # sed -i "/^ChallengeResponseAuthentication/d" /etc/ssh/sshd_config
  # sed -i "/^AuthorizedKeysCommand/d" /etc/ssh/sshd_config
  # sed -i "/^AuthorizedKeysCommandUser/d" /etc/ssh/sshd_config
  # cat <&ltEOF >> /etc/ssh/sshd_config
  ChallengeResponseAuthentication yes
  AuthorizedKeysCommand /opt/authorized_keys_command.sh
  AuthorizedKeysCommandUser nobody
  AuthenticationMethods publickey
  Match User ec2-user
     AuthenticationMethods publickey
     PubkeyAuthentication yes
  EOF
  </pre>

- PAM 設定（google-auth）
  <pre>
  # cat <&ltEOF > /etc/pam.d/google-auth
  #%PAM-1.0
  auth        required      pam_env.so
  auth        sufficient    pam_google_authenticator.so nullok
  auth        requisite     pam_succeed_if.so uid >= 500 quiet
  auth        required      pam_deny.so
  EOF
  </pre>
  <pre>
  # ls -l /etc/pam.d/google-auth
    パーミッションが644であること
    異なる場合は以下のコマンドを実施
    # chmod 644 /etc/pam.d/google-auth
  </pre>

- PAM 設定（sshd）
  <pre>
  # cp -p /etc/pam.d/sshd sshd.org
  # sed -i "s/.*substack/#&/g" /etc/pam.d/sshd
  # sed -i "/substack/a auth       substack     google-auth" /etc/pam.d/sshd
  </pre>

- bash profile作成
  <pre>
  # cat <&ltEOF > /etc/profile.d/google-authenticator.sh
  #!/bin/sh
  
  if [ "$USER" != "root" -a "$USER" != "ec2-user" ]; then
    if [ ! -f "$HOME/.google_authenticator" ]; then
      trap 'exit' SIGINT
      echo "google-authenticator の初期設定を行います"
      /usr/bin/google-authenticator -t -d -W -u -f
      trap -- SIGINT
    fi
  fi
  EOF
  </pre>
  <pre>
  # ls -l /etc/profile.d/google-authenticator.sh
    パーミッションが644であること
    異なる場合は以下のコマンドを実施
    # chmod 644 /etc/profile.d/google-authenticator.sh
  </pre>

- aws-ec2-ssh ツールインストール
  - "IAM_AUTHORIZED_GROUPS"と"SUDOERS_GROUPS"は置き換える
  - 複数グループはカンマで区切る
  - 同期を無効にする場合は"DONOTSYNC"を1に変更
  ※注：インストール前に設定ファイルを作成しておかないとすべてのIAMユーザーが同期される
  <pre>
  # cat <&ltEOF > /etc/aws-ec2-ssh.conf
  IAM_AUTHORIZED_GROUPS="member,admin"
  LOCAL_MARKER_GROUP="iam-synced-users"
  SUDOERS_GROUPS="admin"
  # Remove or set to 0 if you are done with configuration
  # To change the interval of the sync change the file
  # /etc/cron.d/import_users
  DONOTSYNC=0
  EOF
  </pre>
  <pre>
  # ls -l /etc/aws-ec2-ssh.conf
    パーミッションが644であること
    異なる場合は以下のコマンドを実施
    # chmod 644 /etc/aws-ec2-ssh.conf
  </pre>
  <pre>
  # git clone https://github.com/widdix/aws-ec2-ssh.git
  # ./aws-ec2-ssh/install.sh
  </pre>

- cron実行時間の変更
  - デフォルトでは10分毎にIAMユーザーの同期をとる設定になっているため必要であれば変更
  <pre>
  # vi /etc/cron.d/import_users
  </pre>
  <pre>
  # tail -f /var/log/cron | grep import_users.sh
    実行ログが出力されていること
  </pre>
  <pre>
  # cat /etc/passwd
    IAMユーザーが登録されていること
  </pre>

- AMI作成
  - 管理コンソールにてAMIを作成
</details>

<BR>

## ホームディレクトリのデータ退避
- 適当なディレクトリにEFSをマウントし、/homeのデータをコピーする（インスタンス起動時にEFSを/homeにマウントするため）
- 例：EFSのIDは置き換えること
  <pre>
  # mount -t efs fs-0792f22a2bf602d73:/ /mnt
  # cp -rp /home/* /mnt/.
  </pre>
- マウント解除

<BR>

## 起動設定の作成

<details>

- マシンイメージ
  - 作成したAMIを設定

- IAMインスタンスプロファイル
  - 作成したIAMロールを設定

- ユーザーデータ
  - 高度な設定からユーザーデータのテキストボックスに以下を貼り付ける
  - "file_system_id"は置き換える
  <pre>
  #!/bin/bash
  
  ## EFS mount
  export file_system_id=fs-0792f22a2bf602d73
  export efs_directory=/home
  echo ${file_system_id}: ${efs_directory} efs tls,_netdev 0 0 >> /etc/fstab && mount -a -t efs defaults
  
  ## EIP automatic assignment
  INSTANCE_ID=`curl http://169.254.169.254/latest/meta-data/instance-id`
  REGION=`curl http://169.254.169.254/latest/dynamic/instance-identity/document | grep region | awk -F\" '{print $4}'`
  
  for ALLOC_ID in `aws ec2 describe-addresses --region=$REGION --filter "Name=domain,Values=vpc"  --output text | grep eip | awk '{print $2}'`
  do
    CMD="aws ec2 associate-address --instance-id $INSTANCE_ID --allocation-id $ALLOC_ID --no-allow-reassociation --region=$REGION"
    $CMD
    STATUS=$?
    if [ 0 = $STATUS ] ; then
      exit 0
    fi
  done
  exit 1
  </pre>

- セキュリティグループ
  - 作成したEC2用セキュリティグループを設定
- キーペア
  - 作成したキーペアを設定
</details>

<BR>

## AutoScalingグループの作成
- "起動テンプレート"を"起動設定"に切り替える
- プルダウンリストから作成した起動設定を選択
- 作成したVPC、パブリックサブネットを設定
- 容量は任意

<BR>

## 通知用SNSの作成
- バージニアリージョンに作成すること

<BR>

## EC2インスタンス終了用Lambda関数の作成
<details>

- バージニアリージョンに作成すること
- 関数名：任意の文字列
- ランタイム：Python 3.7
- アーキテクチャ：x86_64
- 実行ロール：プルダウンリストから作成したLambda用ロールを選択
- トリガー：作成したSNSトピックを設定
- コード：
  "XXX.XXX.XXX.XXX"は作成したEIPのアドレスに置き換える
  <pre>
  import boto3
  region = 'us-west-2'
  
  def lambda_handler(event, context):
  
      ec2 = boto3.client('ec2', region_name=region)
  
      instance_id = ec2.describe_instances(
          Filters=[{'Name':'network-interface.association.public-ip','Values':["XXX.XXX.XXX.XXX"]}]
      )["Reservations"][0]["Instances"][0]["InstanceId"]
          
      ec2.terminate_instances(InstanceIds=[instance_id])
  
      print('terminate your instances: ' + str(instance_id))
      
      return
  </pre>
</details>

<BR>

## Route53ヘルスチェックの作成
<details>

- ヘルスチェックの作成
  - ssh監視用
    - ヘルスチェックの環境設定
      - 名前：任意の文字列
      - モニタリングの対象：エンドポイント
    - エンドポイントの監視
      - IP アドレス：作成したEIPのアドレスを入力
      - ポート：22
  - nginx監視用
    - ヘルスチェックの環境設定
      - 名前：任意の文字列
      - モニタリングの対象：エンドポイント
    - エンドポイントの監視
      - IP アドレス：作成したEIPのアドレスを入力
      - ポート：80

- アラームの作成
  - 各ヘルスチェックにアラームを設定
    - アラーム名：任意の文字列
    - 通知を送信：はい
      - プルダウンリストから作成したSNSトピックを選択
    - ターゲットをアラーム：ヘルスチェックステータス
    - 条件の履行：最小 < 1
    - 最低発生数：1回 1分

- 作成したアラームにアクションを追加（sshとnginx共通）
  - メトリクス
    - 名前空間：AWS/Route53
    - メトリクス名：HealthCheckPercentageHealthy
    - 統計：平均値
    - 期間：1分
  - 条件
    - しきい値の種類：静的
    - HealthCheckPercentageHealthy が次の時：より低い
    - しきい値：100
  - 通知
    - アラーム状態トリガー：アラーム状態
    - 通知の送信先：プルダウンリストから作成したSNSトピックを選択
    - E メール (エンドポイント)：任意のメールアドレス
</details>

<BR>

## 初回ログイン
- ec2-userでssh接続
- 対象のIAMユーザーにスイッチ
- 下記のコマンドを実行
  <pre>
  $ google-authenticator
    すべて「y」を選択
  $ ls -la
   「.google_authenticator」ファイルが作成されていること
  </pre>
- 表示されたQRコードをスマートフォンのGoogle認証システムで読み込む
- 対象のIAMユーザーでssh接続
- ワンタイムパスワードを入力

### 参考記事
- [Manage AWS EC2 SSH access with IAM](https://github.com/widdix/aws-ec2-ssh)
- [AWS Identity and Access Management (IAM)ユーザを使ってEC2インスタンスのLinuxユーザを管理する](https://www.seeds-std.co.jp/blog/creators/2019-12-25-124247/)
- [aws-ec2-sshでEC2の踏み台サーバのユーザ管理を楽にする](https://qiita.com/bigplants/items/f2d4d15922d87c0d25e4)
- [Amazon LinuxへのsshをGoogle Authenticatorを用いて二段階認証にしてみた](https://dev.classmethod.jp/articles/amazon-linux-ssh-two-step-authentication/)
- [Route 53 ヘルスチェックを使った死活監視](https://oji-cloud.net/2021/07/22/post-6437/)
