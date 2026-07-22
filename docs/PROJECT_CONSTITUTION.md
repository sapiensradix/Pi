# PI PROJECT CONSTITUTION (BẮT BUỘC ĐỌC TRƯỚC MỖI PATCH)

Đây là quy tắc cao nhất của dự án Pi.

Nếu bất kỳ yêu cầu nào mâu thuẫn với tài liệu này thì tài liệu này luôn được ưu tiên.

## Điều 1. Mục tiêu của Pi

Pi là một blockchain PoW gần như giống Bitcoin Core.

Mục tiêu KHÔNG phải tạo một blockchain mới.

Mục tiêu KHÔNG phải cải tiến Bitcoin.

Mục tiêu KHÔNG phải thêm tính năng.

Pi chỉ là:

- blockchain riêng
- genesis riêng
- tên riêng
- nhận diện riêng

Ngoài các thay đổi nhận diện cần thiết, mọi thuật toán phải giữ nguyên như Bitcoin.

## Điều 2. Consensus là vùng cấm

Không được tự ý thay đổi:

- PoW
- SHA-256d
- Difficulty Adjustment
- Halving
- Block Reward
- Total Supply
- Coinbase Maturity
- Script
- UTXO
- Validation
- Mempool Rules
- Transaction Rules
- Block Rules
- Network Rules

Nếu một patch đụng vào bất kỳ phần nào ở trên thì phải DỪNG và báo cáo trước.

Không được tự sửa.

## Điều 3. Chỉ được sửa

Được phép sửa:

- bug
- build
- packaging
- wallet
- GUI
- installer
- documentation
- datadir
- config
- bootstrap
- peer discovery
- release process

## Điều 4. Mining

Pi chỉ hỗ trợ mining trên máy tính.

Không phát triển:

- Android Mining
- iPhone Mining
- Cloud Mining
- Tap-to-mine
- Fake Mining
- Simulation Mining

Mining phải là Proof of Work thật giống Bitcoin.

## Điều 5. Wallet

Wallet chỉ là giao diện.

Wallet KHÔNG được thay đổi blockchain.

Wallet chỉ giúp:

- tạo ví
- gửi
- nhận
- mine
- xem blockchain

## Điều 6. Không được tự ý thêm tính năng

Không được thêm:

- Staking
- POS
- Smart Contract
- Token
- NFT
- DAO
- Governance
- KYC
- Reward mới
- Fee mới

Trừ khi maintainer yêu cầu.

## Điều 7. Nếu không chắc

Nếu patch có khả năng ảnh hưởng consensus hoặc kiến trúc Bitcoin thì:

KHÔNG sửa.

Báo cáo trước.

## Điều 8. Trước khi commit

Luôn xác nhận:

- Không thay đổi consensus.
- Không thay đổi monetary policy.
- Không thay đổi thuật toán.
- Không thay đổi roadmap Bitcoin.

## Điều 9. Mục tiêu cuối cùng

Người dùng sử dụng Pi phải có trải nghiệm giống Bitcoin Core.

Khác biệt chỉ là:

- tên Pi
- blockchain Pi
- logo
- địa chỉ
- genesis
- network identity

Mọi thứ khác phải càng giống Bitcoin càng tốt.

## Điều 10. Không tự đồng bộ với Bitcoin Core mới

Không được tự merge hoặc backport commit từ Bitcoin Core.

Nếu muốn lấy bản vá từ Bitcoin Core thì phải:

- nêu rõ commit hash
- giải thích mục đích
- đánh giá có ảnh hưởng consensus hay không
- chờ maintainer duyệt

Không được tự cập nhật.

## Điều 11. Mỗi patch chỉ có một mục tiêu

Một patch chỉ được giải quyết đúng một vấn đề.

Ví dụ:

Patch 3A

✅ Datadir

Không được tiện tay sửa:

- Wallet
- GUI
- Mining
- Installer
- Tests khác
- Packaging

Nếu phát hiện lỗi khác thì chỉ báo cáo.

Không sửa.

## Điều 12. Không được "refactor cho đẹp"

Đây là lỗi AI rất hay mắc.

Không được:

- đổi tên class
- đổi tên hàm
- đổi kiến trúc
- đổi style
- tối ưu code
- modernize
- cleanup
- refactor

Chỉ vì thấy "đẹp hơn".

Nếu code vẫn chạy đúng thì giữ nguyên.

## Điều 13. Luôn ưu tiên tính tương thích Bitcoin Core

Khi có nhiều cách sửa bug:

Ưu tiên cách mà Bitcoin Core đang làm.

Không tự phát minh cách mới.

## Điều 14. Không thay đổi API công khai

Không tự ý đổi:

- RPC
- CLI
- Config
- Wallet format
- File format

Nếu không thật sự cần.

## Điều 15. Mọi thay đổi phải có bằng chứng

Không được nói:

- "Có thể..."
- "Nên..."
- "Có vẻ..."

Phải đưa:

- file
- dòng
- commit
- log
- test

Nếu không có bằng chứng thì phải ghi rõ:

"Đây chỉ là giả thuyết."

## Điều 16. Release Philosophy

Ưu tiên:

Ổn định

>

Đúng

>

Tương thích Bitcoin

>

Hiệu năng

>

Tính năng mới

Nếu phải chọn giữa:

- thêm tính năng

và

- giữ giống Bitcoin

=> luôn giữ giống Bitcoin.

## Điều 17. Không được thay đổi hành vi (Behavior Preservation)

Trước khi bắt đầu bất kỳ patch nào, Codex phải xác định rõ patch đó thuộc loại nào:

- Behavior-changing (thay đổi hành vi)
- Behavior-preserving (không thay đổi hành vi)

Mặc định:

Mọi patch đều phải là Behavior-preserving.

Ví dụ:

Được phép

- sửa crash
- sửa build
- sửa datadir
- sửa installer
- sửa GUI
- sửa comment
- sửa document
- sửa packaging

=> không làm node hoạt động khác đi.

Không được tự làm

Ví dụ:

- node broadcast khác
- mempool xử lý khác
- mining khác
- validate khác
- RPC trả khác
- relay khác
- wallet tạo transaction khác

=> đây đều là Behavior-changing.

Nếu gặp trường hợp này thì:

- dừng
- báo cáo
- không được code

## Điều 18. Không được đoán ý Maintainer

Codex không được:

- "Tôi nghĩ nên..."
- "Có lẽ maintainer muốn..."
- "Để hiện đại hơn..."

Nó chỉ được làm đúng yêu cầu.

Nếu yêu cầu thiếu thông tin thì phải hỏi hoặc báo cáo.

Không được tự suy diễn.

## Điều 19. Không thay đổi giao thức (Protocol Freeze)

Sau khi mainnet phát hành:

Consensus được xem là đóng băng (Frozen).

Mọi thay đổi ảnh hưởng đến:

- block format
- transaction format
- script
- opcode
- signature
- P2P message
- block validation
- transaction validation
- difficulty
- reward
- halving
- UTXO
- serialization
- network protocol

đều mặc định là:

BỊ CẤM

trừ khi maintainer ra quyết định chính thức rằng đó là một hard fork hoặc soft fork.

Điều này phản ánh thực tế của các blockchain công khai: sau khi đã có người dùng và node chạy mainnet, thay đổi giao thức không còn là việc "sửa code" bình thường nữa.

## Điều 20. Bug Fix ≠ Feature

Codex phải phân loại mọi thay đổi thành một trong ba loại:

- Bug Fix → được phép nếu đúng phạm vi.
- Maintenance → được phép nếu đúng phạm vi.
- Feature → phải xin duyệt.

Không được đổi tên Feature thành Bug Fix để tự triển khai.

Ví dụ:

- sửa crash → Bug Fix.
- sửa build → Maintenance.
- thêm RPC mới → Feature.
- đổi logic mining → Feature.
- đổi hành vi wallet → Feature.

Tao cũng đề nghị một quy trình review cố định

Mỗi patch khi hoàn thành phải kết thúc bằng đúng mẫu này:

```text
Patch: 3B

Classification:
Behavior-preserving

Consensus touched:
NO

Protocol touched:
NO

Wallet behavior changed:
NO

Mining behavior changed:
NO

Network behavior changed:
NO

Public API changed:
NO

Tests:
PASS

Build:
PASS

Ready for Review:
YES
```

Nếu có bất kỳ mục nào là YES ở phần Consensus, Protocol, Mining, Network hoặc Public API thì Codex phải dừng và chờ quyết định của maintainer.

## Điều 21 — WHITEPAPER LÀ VÙNG CẤM TUYỆT ĐỐI

Whitepaper là đặc tả chính thức (Official Specification) của blockchain Pi.

Whitepaper được xem là tài liệu bất biến.

Codex chỉ được phép:

- Đọc Whitepaper.
- Tra cứu Whitepaper.
- Đối chiếu Whitepaper với mã nguồn.
- Chỉ ra điểm khác nhau giữa Whitepaper và code.
- Trích dẫn nội dung Whitepaper khi giải thích hoặc báo cáo.

Codex tuyệt đối KHÔNG được:

- Chỉnh sửa Whitepaper.
- Thêm nội dung.
- Xóa nội dung.
- Đổi tên file.
- Di chuyển file.
- Đổi định dạng.
- Tạo Whitepaper mới.
- Thay thế Whitepaper.
- Stage Whitepaper.
- Commit Whitepaper.
- Push Whitepaper.
- Sinh patch liên quan Whitepaper.
- Đề xuất sửa Whitepaper.
- Dùng bất kỳ công cụ nào làm thay đổi Whitepaper.

Không có bất kỳ ngoại lệ nào.

Nếu maintainer yêu cầu sửa Whitepaper, Codex không được tự thực hiện mà phải trả lời:

"Whitepaper là vùng cấm tuyệt đối theo Pi Project Constitution. Tôi không được phép chỉnh sửa hoặc tạo patch liên quan đến Whitepaper."

### Khi phát hiện code khác Whitepaper

Nếu phát hiện:

Code ≠ Whitepaper

Codex chỉ được phép:

- Chỉ rõ file và dòng code.
- Chỉ rõ mục trong Whitepaper.
- Đưa bằng chứng.
- Dừng lại.

Không được sửa code.

Không được sửa Whitepaper.

Quyết định tiếp theo hoàn toàn thuộc maintainer.

## Điều 22 — CONSTITUTION FREEZE

Pi Project Constitution là quy tắc cao nhất điều chỉnh toàn bộ quá trình phát triển blockchain Pi.

Kể từ khi Điều 1 → Điều 22 được maintainer phê duyệt:

Constitution được xem là FROZEN (ĐÓNG BĂNG).

Không được:

- thêm Điều mới;
- xóa Điều;
- sửa nội dung Điều;
- đổi thứ tự Điều;
- diễn giải lại Điều theo ý riêng;
- tạo phiên bản Constitution khác;
- tạo patch sửa Constitution.

Chỉ Maintainer mới có quyền

- mở khóa Constitution;
- sửa Constitution;
- bổ sung Constitution;
- ban hành phiên bản Constitution mới.

Không ai khác, bao gồm Codex, AI, contributor hoặc lập trình viên, được phép tự thay đổi.

### Trước khi thực hiện bất kỳ patch nào

Codex phải thực hiện đúng trình tự:

1. Đọc `/docs/PROJECT_CONSTITUTION.md`.
2. Xác nhận đã hiểu Constitution.
3. Phân loại patch:
   - Bug Fix
   - Maintenance
   - Feature
4. Xác định:
   - Behavior-preserving hay Behavior-changing.
5. Nếu vi phạm bất kỳ Điều nào trong Constitution:
   - Dừng ngay.
   - Báo cáo bằng chứng.
   - Chờ maintainer quyết định.

Không được tiếp tục code.

### Constitution có hiệu lực cao hơn

Khi có mâu thuẫn, thứ tự ưu tiên là:

1. Maintainer Decision
2. `PROJECT_CONSTITUTION.md`
3. Whitepaper (chỉ để tham chiếu và đối chiếu, không được sửa)
4. Approved Patch Specification
5. Source Code

Nếu có bất kỳ xung đột nào giữa các tài liệu trên:

- Không tự quyết định.
- Không tự sửa code.
- Không tự sửa Whitepaper.
- Không tự sửa Constitution.
- Chỉ báo cáo và chờ maintainer.

### Sau khi Điều 22 được phê duyệt

Tạo một patch Maintenance riêng (không trộn với patch khác) để:

- Tạo `/docs/PROJECT_CONSTITUTION.md` chứa nguyên văn Điều 1 → Điều 22.
- Tạo `/docs/MAINTAINER_GUIDE.md` chứa:
  - Patch workflow.
  - Commit rules.
  - Review checklist.
  - Release checklist.
  - Git flow.
  - Coding conventions.
  - Quy trình đọc Constitution trước mỗi patch.

Patch này phải là:

- Classification: Maintenance
- Behavior: Behavior-preserving
- Consensus touched: NO
- Protocol touched: NO
- Public API changed: NO

Sau khi hai file được commit, Constitution chính thức có hiệu lực và được xem là tài liệu bất biến, chỉ maintainer mới có quyền thay đổi trong tương lai.
