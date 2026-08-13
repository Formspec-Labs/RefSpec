import java.nio.file.Path;

import org.apache.jena.rdf.model.Model;
import org.apache.jena.rdf.model.ModelFactory;
import org.apache.jena.rdf.model.Property;
import org.apache.jena.rdf.model.Resource;
import org.apache.jena.riot.RDFDataMgr;
import org.topbraid.shacl.validation.ValidationUtil;

/**
 * Minimal bounded-scale runner for the TopBraid SHACL API.
 *
 * <p>The runner reports load and validation separately and emits only a compact
 * summary, so serializing a large validation report cannot distort the timing.
 */
public final class TopBraidValidate {
    private static final String SH = "http://www.w3.org/ns/shacl#";

    private TopBraidValidate() {}

    public static void main(String[] args) {
        if (args.length != 2) {
            System.err.println("usage: TopBraidValidate DATA SHAPES");
            System.exit(2);
        }

        long started = System.nanoTime();
        Model data = ModelFactory.createDefaultModel();
        RDFDataMgr.read(data, Path.of(args[0]).toUri().toString());
        Model shapes = ModelFactory.createDefaultModel();
        RDFDataMgr.read(shapes, Path.of(args[1]).toUri().toString());
        long loaded = System.nanoTime();

        Resource report = ValidationUtil.validateModel(data, shapes, false);
        long validated = System.nanoTime();

        Property conformsProperty = report.getModel().createProperty(SH + "conforms");
        Property resultProperty = report.getModel().createProperty(SH + "result");
        boolean conforms = report.getRequiredProperty(conformsProperty).getBoolean();
        long results = report.listProperties(resultProperty).toList().size();

        System.out.printf(
                "engine=topbraid-shacl data_triples=%d shape_triples=%d "
                        + "load_seconds=%.3f validate_seconds=%.3f total_seconds=%.3f "
                        + "conforms=%s results=%d%n",
                data.size(),
                shapes.size(),
                seconds(loaded - started),
                seconds(validated - loaded),
                seconds(validated - started),
                conforms,
                results);
    }

    private static double seconds(long nanoseconds) {
        return nanoseconds / 1_000_000_000.0;
    }
}
