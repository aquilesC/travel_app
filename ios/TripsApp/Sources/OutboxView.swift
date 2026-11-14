import SwiftUI
import TripsKit

/// Everything waiting to be sent, with progress and what to do about problems (ios #5).
struct OutboxView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openURL) private var openURL

    var body: some View {
        List {
            ForEach(model.outboxItems.reversed()) { item in
                VStack(alignment: .leading, spacing: 4) {
                    Text(title(item)).font(.headline).lineLimit(2)
                    Text(detail(item)).font(.caption).foregroundStyle(.secondary)
                    if let error = item.lastError, item.isPending { Text(error).font(.caption).foregroundStyle(.orange) }
                    if case .failed(let reason) = item.state { Text(reason).font(.caption).foregroundStyle(.red) }
                    actions(item)
                }
                .padding(.vertical, 2)
                .swipeActions {
                    if item.isPending || isFailed(item) {
                        Button("Delete", role: .destructive) { Task { await model.discard(item.id) } }
                    }
                }
            }
        }
        .navigationTitle("Outbox")
        .refreshable { model.kick() }
        .overlay {
            if model.outboxItems.isEmpty { ContentUnavailableView("Nothing waiting", systemImage: "tray") }
        }
    }

    @ViewBuilder private func actions(_ item: OutboxItem) -> some View {
        HStack {
            if item.isPending, item.lastError == "Waiting for wifi (large files)." {
                Button("Send now anyway") { Task { await model.sendAnyway(item.id) } }
            }
            if isFailed(item) { Button("Retry") { Task { await model.retry(item.id) } } }
            if case .photoImport = item.kind, case .done(let batch) = item.state {
                Button("Review on the website") { openURL(model.reviewURL(batchID: batch)) }
            }
        }
        .buttonStyle(.borderless)
        .font(.caption)
    }

    private func isFailed(_ item: OutboxItem) -> Bool {
        if case .failed = item.state { return true }
        return false
    }

    private func title(_ item: OutboxItem) -> String {
        switch item.kind {
        case .post(let draft):
            let text = draft.body.trimmingCharacters(in: .whitespacesAndNewlines)
            return text.isEmpty ? "Post with \(item.files.count) file(s)" : text
        case .photoImport: return "\(item.files.count) photos for review"
        }
    }

    private func detail(_ item: OutboxItem) -> String {
        let size = ByteCountFormatter.string(fromByteCount: Int64(item.totalBytes), countStyle: .file)
        let when = item.createdAt.formatted(date: .omitted, time: .shortened)
        switch item.state {
        case .pending:
            let done = item.files.filter(\.done).count
            return "\(when) · \(size) · \(done)/\(item.files.count) files sent"
        case .done: return "\(when) · sent"
        case .failed: return "\(when) · needs you"
        }
    }
}
