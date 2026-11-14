import SwiftUI

struct LoginView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.openURL) private var openURL
    @State private var email = ""
    @State private var password = ""
    @State private var busy = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Email", text: $email)
                        .textContentType(.username)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    SecureField("Password", text: $password)
                        .textContentType(.password)
                } footer: {
                    Text("The same account as on \(model.server.host() ?? "the website"). New accounts come from an invite.")
                }
                if let error = model.errorMessage {
                    Section { Text(error).foregroundStyle(.red) }
                }
                Section {
                    Button {
                        busy = true
                        Task {
                            await model.login(email: email.trimmingCharacters(in: .whitespaces), password: password)
                            busy = false
                        }
                    } label: {
                        if busy { ProgressView() } else { Text("Log in").frame(maxWidth: .infinity) }
                    }
                    .disabled(email.isEmpty || password.isEmpty || busy)
                    Button("Forgot password?") {
                        openURL(model.server.appending(path: "accounts/password/reset/"))
                    }
                }
            }
            .navigationTitle("Trips")
        }
    }
}
