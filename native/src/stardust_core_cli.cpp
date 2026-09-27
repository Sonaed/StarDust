#include "stardust_core.hpp"

#include <iostream>
#include <regex>
#include <string>

using stardust::Graph;

static std::string value(const std::string& line, const std::string& key) {
    std::regex pattern("\\\"" + key + "\\\"\\s*:\\s*\\\"([^\\\"]*)\\\"");
    std::smatch match;
    return std::regex_search(line, match, pattern) ? match[1].str() : "";
}

int main() {
    Graph graph;
    std::string line;
    while (std::getline(std::cin, line)) {
        const auto command = value(line, "command");
        bool ok = true;
        std::string result;
        if (command == "reset") graph.reset(value(line, "creator"));
        else if (command == "add_node") ok = graph.add_node(value(line, "id"), value(line, "type"));
        else if (command == "remove_node") ok = graph.remove_node(value(line, "id"));
        else if (command == "connect") ok = graph.connect(value(line, "from"), value(line, "to"));
        else if (command == "set_parameter") ok = graph.set_parameter(value(line, "key"), value(line, "value"));
        else if (command == "validate") {
            const auto errors = graph.validate();
            result = "[";
            for (size_t i = 0; i < errors.size(); ++i) result += (i ? "," : "") + std::string("\"") + errors[i] + "\"";
            result += "]";
            ok = errors.empty();
        } else if (command == "serialize" || command == "snapshot") result = graph.serialize();
        else ok = false;
        if (result.empty()) result = ok ? "true" : "false";
        std::cout << "{\"ok\":" << (ok ? "true" : "false") << ",\"result\":" << result << "}\n" << std::flush;
    }
    return 0;
}
